import json
import logging
import os

from otto_complete.bots.base import BaseBot
from otto_complete.config import Watcher
from otto_complete.review import (
    collect_unaddressed_comments,
    format_comments_for_prompt,
    post_review_replies,
    auto_resolve_review_threads,
    mark_issue_comments_seen,
)

log = logging.getLogger(__name__)


class ImplementerBot(BaseBot):
    name = "implementer"

    def run_pass(self, watcher: Watcher):
        cfg = self.config

        # Recovery: ai:error (auto-recover if open PR exists)
        errored = self.jira.query_by_label(watcher.project, "ai:error", watcher.component)
        for issue_key in errored:
            self._recover_error(issue_key)

        # Recovery: ai:implementing
        stuck = self.jira.query_by_label(watcher.project, "ai:implementing", watcher.component)
        for issue_key in stuck:
            self._recover(issue_key)

        # Recovery: ai:ci-fixing
        stuck_ci = self.jira.query_by_label(watcher.project, "ai:ci-fixing", watcher.component)
        for issue_key in stuck_ci:
            self._recover_ci_fixer(issue_key)

        # Normal: implement merged plans
        plan_issues = self.jira.query_by_label(watcher.project, "ai:plan-review", watcher.component)
        for issue_key in plan_issues:
            self._check_and_implement(issue_key)

        # CI monitoring (before review comments)
        impl_issues = self.jira.query_by_label(watcher.project, "ai:impl-review", watcher.component)
        for issue_key in impl_issues:
            self._check_and_fix_ci(issue_key)

        # Review comments
        impl_issues = self.jira.query_by_label(watcher.project, "ai:impl-review", watcher.component)
        for issue_key in impl_issues:
            self._address_comments(issue_key)

    def _recover_error(self, issue_key: str):
        branch = f"{self.config.branch_prefix_impl}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)
        if pr_number and not self.github.pr_is_merged(pr_number):
            log.info("%s: recovering from ai:error — open PR #%d found, moving to impl-review", issue_key, pr_number)
            self._reset_ci_attempts(issue_key)
            self.jira.swap_label(issue_key, "ai:error", "ai:impl-review")

    def _recover(self, issue_key: str):
        branch = f"{self.config.branch_prefix_impl}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)

        if pr_number:
            log.info("%s: recovering — impl PR #%d exists, fixing label", issue_key, pr_number)
            self.jira.swap_label(issue_key, "ai:implementing", "ai:impl-review")
            return

        plan_branch = f"{self.config.branch_prefix_plan}{issue_key}"
        plan_pr = self.github.find_pr_by_branch(plan_branch)
        if not plan_pr or not self.github.pr_is_merged(plan_pr):
            log.warning("%s: recovering — no impl PR and plan not merged, cannot retry", issue_key)
            return

        log.info("%s: recovering — no impl PR found, retrying implementation", issue_key)
        self._implement_issue(issue_key)

    def _recover_ci_fixer(self, issue_key: str):
        branch = f"{self.config.branch_prefix_impl}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)

        if not pr_number:
            log.warning("%s: recovering ci-fixing — no impl PR found, moving to error", issue_key)
            self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: CI fixing recovery failed — no impl PR found")
            return

        log.info("%s: recovering ci-fixing — impl PR #%d exists, returning to impl-review", issue_key, pr_number)
        self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:impl-review")

    def _check_and_implement(self, issue_key: str):
        cfg = self.config
        plan_branch = f"{cfg.branch_prefix_plan}{issue_key}"
        pr_number = self.github.find_pr_by_branch(plan_branch)

        if not pr_number:
            log.warning("%s: no plan PR found for branch %s", issue_key, plan_branch)
            return

        if not self.github.pr_is_merged(pr_number):
            log.info("%s: plan PR #%d not yet merged", issue_key, pr_number)
            return

        log.info("%s: plan PR #%d merged, starting implementation", issue_key, pr_number)
        if not self.jira.swap_label(issue_key, "ai:plan-review", "ai:implementing"):
            return

        self._implement_issue(issue_key)

    def _implement_issue(self, issue_key: str):
        cfg = self.config

        self.git.ensure_repo_cloned()
        branch = f"{cfg.branch_prefix_impl}{issue_key}"
        self.git.create_branch(branch)

        plan_file = os.path.join(self.spec_dir(issue_key), "plan.md")
        if not os.path.isfile(plan_file):
            log.error("Plan file not found after merge: %s", plan_file)
            self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Plan file missing from merged branch")
            return

        prompt = self.render_template("implement-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir)

        log.info("Running Claude for %s (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_impl, cfg.max_budget_impl)

        self.run_claude_on_repo("implementer", issue_key, prompt,
            "Read,Write,Edit,Bash", cfg.max_turns_impl, cfg.max_budget_impl)

        changes = self.git.status()
        if not changes:
            log.error("No changes produced for %s", issue_key)
            self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Implementation produced no changes")
            return

        log.info("Implementation produced changes, committing")
        self.git.add()
        self.git.commit(f"{issue_key}: implement plan")
        self.git.push_branch(branch)

        summary, _ = self.jira.get_details(issue_key)
        spec_pr = self.github.find_pr_by_branch(f"{cfg.branch_prefix_spec}{issue_key}")
        plan_pr = self.github.find_pr_by_branch(f"{cfg.branch_prefix_plan}{issue_key}")

        pr_body = (
            f"## {issue_key}: {summary}\n\n"
            f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
            f"**Spec PR:** #{spec_pr}\n"
            f"**Plan PR:** #{plan_pr}\n\n"
            f"Implementation of the approved plan.\n\n"
            f"See:\n"
            f"- `{cfg.specs_dir}/{issue_key}/spec.md` — specification\n"
            f"- `{cfg.specs_dir}/{issue_key}/plan.md` — implementation plan\n"
            f"- `{cfg.specs_dir}/{issue_key}/tasks.md` — task breakdown"
        )

        pr_url = self.github.create_pr(branch, f"{issue_key}: {summary}", pr_body, cfg.default_branch, "ai:impl")

        if not pr_url or "error" in pr_url.lower():
            log.error("Failed to create impl PR for %s: %s", issue_key, pr_url)
            self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
            self.jira.add_comment(issue_key, f"otto-complete error: Impl PR creation failed: {pr_url}")
            return

        self._reset_ci_attempts(issue_key)
        self.jira.swap_label(issue_key, "ai:implementing", "ai:impl-review")
        self.jira.add_comment(issue_key, f"Implementation PR opened: {pr_url}")
        log.info("Implementation PR created for %s: %s", issue_key, pr_url)

    def _check_and_fix_ci(self, issue_key: str):
        cfg = self.config
        impl_branch = f"{cfg.branch_prefix_impl}{issue_key}"
        pr_number = self.github.find_pr_by_branch(impl_branch)
        if not pr_number:
            return

        if self.github.pr_is_merged(pr_number):
            return

        if self.github.checks_are_pending(pr_number):
            log.info("%s: CI checks still pending on PR #%d, skipping", issue_key, pr_number)
            return

        if self.github.all_checks_pass(pr_number):
            return

        failed_checks = self.github.get_failed_checks(pr_number)
        if not failed_checks:
            return

        attempt_count = self._get_ci_attempts(issue_key)

        if attempt_count >= cfg.ci_max_retries:
            log.warning("%s: CI fix attempts exhausted (%d >= %d)", issue_key, attempt_count, cfg.ci_max_retries)
            self.jira.swap_label(issue_key, "ai:impl-review", "ai:error")
            self.jira.add_comment(issue_key,
                f"otto-complete error: CI checks failed after {attempt_count} fix attempts. Manual intervention required.")
            return

        next_attempt = attempt_count + 1
        self._set_ci_attempts(issue_key, next_attempt)
        log.info("%s: CI failures detected on PR #%d, fix attempt %d/%d",
                 issue_key, pr_number, next_attempt, cfg.ci_max_retries)

        if not self.jira.swap_label(issue_key, "ai:impl-review", "ai:ci-fixing"):
            return

        self._perform_ci_fix(issue_key, pr_number, impl_branch, failed_checks, next_attempt)

        self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:impl-review")

    def _perform_ci_fix(self, issue_key: str, pr_number: int, impl_branch: str,
                        failed_checks: list[dict], attempt_number: int):
        cfg = self.config

        self.git.ensure_repo_cloned()
        self.git.checkout_branch(impl_branch)

        analysis_file = os.path.join(self.spec_dir(issue_key), "ci-analysis.json")
        replies_file_path = self.replies_file(issue_key)
        self.git.remove_file(os.path.relpath(analysis_file, cfg.clone_path))
        self.git.remove_file(os.path.relpath(replies_file_path, cfg.clone_path))

        failed_checks_text = self.github.format_failed_checks(failed_checks)
        log_urls = "\n".join(c.get("link", "") for c in failed_checks[:10] if c.get("link"))

        prompt = self.render_template("ci-fix-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir,
            PR_NUMBER=str(pr_number), ATTEMPT_NUMBER=str(attempt_number),
            MAX_ATTEMPTS=str(cfg.ci_max_retries),
            FAILED_CHECKS=failed_checks_text,
            LOG_URLS=log_urls)

        log.info("Running Claude for %s CI fix (attempt %d, max %d turns, $%s budget)",
                 issue_key, attempt_number, cfg.max_turns_ci_fix, cfg.max_budget_ci_fix)

        self.run_claude_on_repo("implementer-ci-fix", issue_key, prompt,
            "Read,Write,Edit,Bash", cfg.max_turns_ci_fix, cfg.max_budget_ci_fix)

        is_flake = False
        fix_summary = "Claude analysis completed"

        if os.path.isfile(analysis_file):
            try:
                with open(analysis_file) as f:
                    analysis = json.load(f)
                is_flake = analysis.get("flake", False)
                fix_summary = analysis.get("summary", "No summary provided")
            except Exception:
                log.warning("%s: failed to parse ci-analysis.json", issue_key)
            os.remove(analysis_file)
        else:
            log.warning("%s: no ci-analysis.json produced", issue_key)

        if is_flake:
            log.info("%s: CI failure identified as flake, posting /retest", issue_key)
            self.github.comment_on_pr(pr_number, "/retest")
            self.jira.add_comment(issue_key, f"CI fix attempt {attempt_number}: Flake detected — {fix_summary}")
            return

        changes = self.git.status()
        if changes:
            log.info("%s: CI fix produced changes, committing", issue_key)
            self.git.add()
            self.git.commit(f"{issue_key}: CI fix attempt {attempt_number}")
            if self.git.push_branch(impl_branch, force=True):
                self.jira.add_comment(issue_key, f"CI fix attempt {attempt_number}: {fix_summary}")
            else:
                log.warning("%s: push failed for CI fix", issue_key)
        else:
            log.warning("%s: CI fix attempt %d produced no changes", issue_key, attempt_number)
            self.jira.add_comment(issue_key,
                f"CI fix attempt {attempt_number}: No code changes produced — {fix_summary}")

    def _ci_attempts_file(self, issue_key: str) -> str:
        return os.path.join(self.config.work_dir, f".ci-attempts-{issue_key}")

    def _get_ci_attempts(self, issue_key: str) -> int:
        path = self._ci_attempts_file(issue_key)
        try:
            with open(path) as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _set_ci_attempts(self, issue_key: str, count: int):
        path = self._ci_attempts_file(issue_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(count))

    def _reset_ci_attempts(self, issue_key: str):
        path = self._ci_attempts_file(issue_key)
        if os.path.exists(path):
            os.remove(path)
            log.info("%s: CI attempt counter reset", issue_key)

    def _address_comments(self, issue_key: str):
        cfg = self.config
        impl_branch = f"{cfg.branch_prefix_impl}{issue_key}"
        pr_number = self.github.find_pr_by_branch(impl_branch)
        if not pr_number:
            return

        comments = collect_unaddressed_comments(self.github, pr_number)
        if not comments:
            return

        log.info("%s: found unaddressed review comments on impl PR #%d", issue_key, pr_number)
        self.git.ensure_repo_cloned()
        self.git.checkout_branch(impl_branch)

        replies_file_path = self.replies_file(issue_key)
        self.git.remove_file(os.path.relpath(replies_file_path, cfg.clone_path))

        formatted = format_comments_for_prompt(comments)
        prompt = self.render_template("impl-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir, COMMENTS=formatted)

        log.info("Running Claude for %s impl review (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_review, cfg.max_budget_review)

        self.run_claude_on_repo("implementer-review", issue_key, prompt,
            "Read,Write,Edit,Bash", cfg.max_turns_review, cfg.max_budget_review)

        changes = self.git.status()
        if changes:
            log.info("%s: impl updated, committing", issue_key)
            self.git.remove_file(os.path.relpath(replies_file_path, cfg.clone_path))
            self.git.add()
            self.git.commit(f"{issue_key}: address impl review comments")
            self.git.push_branch(impl_branch, force=True)
            self._reset_ci_attempts(issue_key)

        post_review_replies(self.github, issue_key, pr_number, comments, replies_file_path)
