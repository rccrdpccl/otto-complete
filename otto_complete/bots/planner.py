import logging
import os

from otto_complete.bots.base import BaseBot
from otto_complete.config import Watcher
from otto_complete.review import (
    collect_unaddressed_comments,
    format_comments_for_prompt,
    post_review_replies,
)

log = logging.getLogger(__name__)


class PlannerBot(BaseBot):
    name = "planner"

    def run_pass(self, watcher: Watcher):
        cfg = self.config

        # Recovery pass
        stuck = self.jira.query_by_label(watcher.project, "ai:planning", watcher.component)
        for issue_key in stuck:
            self._recover(issue_key)

        # Normal pass
        issues = self.jira.query_by_label(watcher.project, "ai:spec-review", watcher.component)
        if not issues:
            log.info("No issues awaiting planning for %s%s",
                     watcher.project, f"/{watcher.component}" if watcher.component else "")
        for issue_key in issues:
            self._check_and_plan(issue_key)

        # Review pass
        review_issues = self.jira.query_by_label(watcher.project, "ai:plan-review", watcher.component)
        for issue_key in review_issues:
            self._address_comments(issue_key)

    def _recover(self, issue_key: str):
        branch = f"{self.config.branch_prefix_plan}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)

        if pr_number:
            log.info("%s: recovering — plan PR #%d exists, fixing label", issue_key, pr_number)
            self.jira.swap_label(issue_key, "ai:planning", "ai:plan-review")
            return

        spec_branch = f"{self.config.branch_prefix_spec}{issue_key}"
        spec_pr = self.github.find_pr_by_branch(spec_branch)
        if not spec_pr or not self.github.pr_is_merged(spec_pr):
            log.warning("%s: recovering — no plan PR and spec not merged, cannot retry", issue_key)
            return

        log.info("%s: recovering — no plan PR found, retrying planning", issue_key)
        self._plan_issue(issue_key)

    def _check_and_plan(self, issue_key: str):
        cfg = self.config
        spec_branch = f"{cfg.branch_prefix_spec}{issue_key}"
        pr_number = self.github.find_pr_by_branch(spec_branch)

        if not pr_number:
            log.warning("%s: no spec PR found for branch %s", issue_key, spec_branch)
            return

        if not self.github.pr_is_merged(pr_number):
            log.info("%s: spec PR #%d not yet merged", issue_key, pr_number)
            return

        log.info("%s: spec PR #%d merged, starting planning", issue_key, pr_number)
        if not self.jira.swap_label(issue_key, "ai:spec-review", "ai:planning"):
            return

        self._plan_issue(issue_key)

    def _plan_issue(self, issue_key: str):
        cfg = self.config

        self.git.ensure_repo_cloned()
        branch = f"{cfg.branch_prefix_plan}{issue_key}"
        self.git.create_branch(branch)

        spec_file = os.path.join(self.spec_dir(issue_key), "spec.md")
        if not os.path.isfile(spec_file):
            log.error("Spec file not found after merge: %s", spec_file)
            self.jira.swap_label(issue_key, "ai:planning", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Spec file missing from merged branch")
            return

        prompt = self.render_template("plan-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir)

        log.info("Running Claude for %s (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_plan, cfg.max_budget_plan)

        tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(git log*),Bash(git diff*),Bash(ls *),Bash(cat *)"
        self.run_claude_on_repo("planner", issue_key, prompt, tools, cfg.max_turns_plan, cfg.max_budget_plan)

        plan_file = os.path.join(self.spec_dir(issue_key), "plan.md")
        if not os.path.isfile(plan_file):
            log.error("Claude did not produce plan file: %s", plan_file)
            self.jira.swap_label(issue_key, "ai:planning", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Plan file not created")
            return

        tasks_file = os.path.join(self.spec_dir(issue_key), "tasks.md")
        if not os.path.isfile(tasks_file):
            log.warning("Tasks file not created: %s (continuing without it)", tasks_file)

        log.info("Plan files created, committing")
        self.git.add(os.path.join(cfg.specs_dir, issue_key))
        self.git.commit(f"{issue_key}(plan): create implementation plan and tasks")
        self.git.push_branch(branch)

        summary, _ = self.jira.get_details(issue_key)
        spec_pr_number = self.github.find_pr_by_branch(f"{cfg.branch_prefix_spec}{issue_key}")

        pr_body = (
            f"## Implementation Plan for {issue_key}\n\n"
            f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
            f"**Summary:** {summary}\n"
            f"**Spec PR:** #{spec_pr_number}\n\n"
            f"This PR contains the implementation plan and task breakdown.\n"
            f"Review the files at:\n"
            f"- `{cfg.specs_dir}/{issue_key}/plan.md` — technical approach and design decisions\n"
            f"- `{cfg.specs_dir}/{issue_key}/tasks.md` — ordered task breakdown\n\n"
            f"### Review checklist\n"
            f"- [ ] Plan approach is sound and follows existing patterns\n"
            f"- [ ] Task ordering is correct (dependencies respected)\n"
            f"- [ ] Testing strategy covers acceptance criteria from the spec\n"
            f"- [ ] Risks are identified and mitigated\n\n"
            f"Once merged, the implementer bot will execute these tasks and open a follow-up PR."
        )

        pr_url = self.github.create_pr(branch, f"plan: {issue_key} {summary}", pr_body, cfg.default_branch, "ai:plan")

        if not pr_url or "error" in pr_url.lower():
            log.error("Failed to create PR for %s: %s", issue_key, pr_url)
            self.jira.swap_label(issue_key, "ai:planning", "ai:error")
            self.jira.add_comment(issue_key, f"otto-complete error: Plan PR creation failed: {pr_url}")
            return

        self.jira.swap_label(issue_key, "ai:planning", "ai:plan-review")
        self.jira.add_comment(issue_key, f"Implementation plan PR opened: {pr_url}")
        log.info("Plan PR created for %s: %s", issue_key, pr_url)

    def _address_comments(self, issue_key: str):
        cfg = self.config
        branch = f"{cfg.branch_prefix_plan}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)
        if not pr_number:
            return

        comments = collect_unaddressed_comments(self.github, pr_number)
        if not comments:
            return

        log.info("%s: found unaddressed review comments on plan PR #%d", issue_key, pr_number)
        self.git.ensure_repo_cloned()
        self.git.checkout_branch(branch)

        formatted = format_comments_for_prompt(comments)
        prompt = self.render_template("plan-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir, COMMENTS=formatted)

        log.info("Running Claude for %s plan review (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_review, cfg.max_budget_review)

        tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(cat *),Bash(ls *)"
        self.run_claude_on_repo("planner-review", issue_key, prompt, tools, cfg.max_turns_review, cfg.max_budget_review)

        spec_path = os.path.join(cfg.specs_dir, issue_key)
        changes = self.git.status(spec_path)
        if changes:
            log.info("%s: plan updated, committing", issue_key)
            self.git.add(spec_path)
            self.git.commit(f"{issue_key}(plan): address review comments")
            self.git.push_branch(branch, force=True)

        post_review_replies(self.github, issue_key, pr_number, comments, self.replies_file(issue_key))
