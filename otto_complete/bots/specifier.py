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


class SpecifierBot(BaseBot):
    name = "specifier"

    def run_pass(self, watcher: Watcher):
        cfg = self.config

        # Recovery pass
        stuck = self.jira.query_by_label(watcher.project, "ai:specifying", watcher.component)
        for issue_key in stuck:
            self._recover(issue_key)

        # Normal pass
        new_issues = self.jira.query_new_issues(watcher.project, cfg.label, watcher.component)
        if not new_issues:
            log.info("No new issues for %s%s with label %s",
                     watcher.project, f"/{watcher.component}" if watcher.component else "", cfg.label)
        for issue_key in new_issues:
            self._process(issue_key)

        # Review pass
        review_issues = self.jira.query_by_label(watcher.project, "ai:spec-review", watcher.component)
        for issue_key in review_issues:
            self._address_comments(issue_key)

    def _recover(self, issue_key: str):
        branch = f"{self.config.branch_prefix_spec}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)

        if pr_number:
            log.info("%s: recovering — spec PR #%d exists, fixing label", issue_key, pr_number)
            self.jira.swap_label(issue_key, "ai:specifying", "ai:spec-review")
        else:
            log.info("%s: recovering — no spec PR found, retrying from scratch", issue_key)
            self.jira.remove_label(issue_key, "ai:specifying")
            self._process(issue_key)

    def _process(self, issue_key: str):
        cfg = self.config

        log.info("Specifying %s", issue_key)
        if not self.jira.add_label(issue_key, "ai:specifying"):
            return

        summary, description = self.jira.get_details(issue_key)
        if not summary:
            log.error("Failed to fetch JIRA details for %s", issue_key)
            self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Failed to fetch JIRA details")
            return

        self.git.ensure_repo_cloned()
        branch = f"{cfg.branch_prefix_spec}{issue_key}"
        self.git.create_branch(branch)

        spec_dir = self.spec_dir(issue_key)
        os.makedirs(spec_dir, exist_ok=True)

        prompt = self.render_template("spec-prompt.md",
            ISSUE_KEY=issue_key, SUMMARY=summary,
            DESCRIPTION=description, SPECS_DIR=cfg.specs_dir)

        log.info("Running Claude for %s (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_spec, cfg.max_budget_spec)

        tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(git log*),Bash(git diff*),Bash(ls *),Bash(cat *)"
        self.run_claude_on_repo("specifier", issue_key, prompt, tools, cfg.max_turns_spec, cfg.max_budget_spec)

        spec_file = os.path.join(spec_dir, "spec.md")
        if not os.path.isfile(spec_file):
            log.error("Claude did not produce spec file: %s", spec_file)
            self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
            self.jira.add_comment(issue_key, "otto-complete error: Spec file not created")
            return

        log.info("Spec file created, committing")
        self.git.add(os.path.join(cfg.specs_dir, issue_key))
        self.git.commit(f"{issue_key}(spec): create specification")
        self.git.push_branch(branch)

        pr_body = (
            f"## Specification for {issue_key}\n\n"
            f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
            f"**Summary:** {summary}\n\n"
            f"This PR contains a formal specification — **what** to build and **why**.\n"
            f"Review the spec at `{cfg.specs_dir}/{issue_key}/spec.md`.\n\n"
            f"### Review checklist\n"
            f"- [ ] Requirements are clear and testable\n"
            f"- [ ] Acceptance criteria are complete\n"
            f"- [ ] Out of scope is correctly defined\n"
            f"- [ ] Open questions are answered (edit the spec if needed)\n\n"
            f"Once merged, the planner bot will generate an implementation plan as a follow-up PR."
        )

        pr_url = self.github.create_pr(branch, f"spec: {issue_key} {summary}", pr_body, cfg.default_branch, "ai:spec")

        if not pr_url or "error" in pr_url.lower():
            log.error("Failed to create PR for %s: %s", issue_key, pr_url)
            self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
            self.jira.add_comment(issue_key, f"otto-complete error: Spec PR creation failed: {pr_url}")
            return

        self.jira.swap_label(issue_key, "ai:specifying", "ai:spec-review")
        self.jira.add_comment(issue_key, f"Specification PR opened: {pr_url}")
        self.jira.transition(issue_key, "In Progress")
        log.info("Spec PR created for %s: %s", issue_key, pr_url)

    def _address_comments(self, issue_key: str):
        cfg = self.config
        branch = f"{cfg.branch_prefix_spec}{issue_key}"
        pr_number = self.github.find_pr_by_branch(branch)
        if not pr_number:
            return

        comments = collect_unaddressed_comments(self.github, pr_number)
        if not comments:
            return

        log.info("%s: found unaddressed review comments on PR #%d", issue_key, pr_number)
        self.git.ensure_repo_cloned()
        self.git.checkout_branch(branch)

        formatted = format_comments_for_prompt(comments)
        prompt = self.render_template("spec-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=cfg.specs_dir, COMMENTS=formatted)

        log.info("Running Claude for %s review (max %d turns, $%s budget)",
                 issue_key, cfg.max_turns_review, cfg.max_budget_review)

        tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(cat *),Bash(ls *)"
        self.run_claude_on_repo("specifier-review", issue_key, prompt, tools, cfg.max_turns_review, cfg.max_budget_review)

        spec_path = os.path.join(cfg.specs_dir, issue_key, "spec.md")
        changes = self.git.status(spec_path)
        if changes:
            log.info("%s: spec updated, committing", issue_key)
            self.git.add(spec_path)
            self.git.commit(f"{issue_key}(spec): address review comments")
            self.git.push_branch(branch, force=True)

        post_review_replies(self.github, issue_key, pr_number, comments, self.replies_file(issue_key))
