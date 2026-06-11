import logging
import os

from otto_complete.config import Config, Watcher, RepoContext, SourceRepo
from otto_complete.clients.jira import JiraClient
from otto_complete.claude_runner import run_claude

log = logging.getLogger(__name__)

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.normpath(os.path.join(_PACKAGE_ROOT, "..", "templates"))


class BaseBot:
    name = "base"

    def __init__(self, config: Config, jira: JiraClient,
                 spec_ctx: RepoContext, impl_ctx: RepoContext,
                 source_repos: list[SourceRepo] | None = None):
        self.config = config
        self.jira = jira
        self.spec_ctx = spec_ctx
        self.impl_ctx = impl_ctx
        self.source_repos: list[SourceRepo] = source_repos or []

    def run_pass(self, watcher: Watcher):
        raise NotImplementedError

    def render_template(self, template_name: str, **kwargs) -> str:
        template_path = os.path.join(TEMPLATES_DIR, template_name)
        with open(template_path) as f:
            content = f.read()
        for key, value in kwargs.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))
        return content

    def run_claude_on_repo(
        self, bot_name: str, issue_key: str, prompt: str,
        tools: str, max_turns: int, max_budget: str,
        clone_path: str,
    ) -> int:
        exit_code, _ = run_claude(bot_name, issue_key, prompt, tools, max_turns, max_budget, clone_path)
        return exit_code

    def ensure_source_repos_cloned(self):
        for src in self.source_repos:
            src.git.ensure_repo_cloned()

    def format_source_repos_section(self) -> str:
        if not self.source_repos:
            return ""
        lines = [
            "## Source Repositories (Read-Only Reference)\n",
            "The following repositories are cloned locally for reference. "
            "Do NOT modify them.\n",
            "**CRITICAL: Before proposing or implementing changes to any Kubernetes/OpenShift "
            "resources defined by these repos, you MUST examine their API type definitions "
            "to understand the correct resource schema.** Specifically:\n",
            "1. Search for API type definitions: `find <repo_path> -name '*_types.go'` or "
            "`find <repo_path> -path '*/api/*' -name '*.go'`",
            "2. Read the type structs to understand field names, nesting, and JSON tags",
            "3. Check which fields belong to which resource (e.g., a field may be on the "
            "bootstrap config, not the control plane)",
            "4. Use the exact field paths from the CRD types — do not guess or assume\n",
        ]
        for src in self.source_repos:
            entry = f"- **{src.repo}** (branch: {src.branch}): `{src.clone_path}`"
            if src.description:
                entry += f"\n  {src.description}"
            lines.append(entry)
        return "\n".join(lines)

    def _is_pr_closed(self, github, pr_number: int) -> bool:
        return github.pr_state(pr_number) == "CLOSED"

    def spec_dir(self, issue_key: str) -> str:
        return os.path.join(self.spec_ctx.clone_path, self.spec_ctx.specs_dir, issue_key)

    def replies_file(self, issue_key: str) -> str:
        return os.path.join(self.spec_dir(issue_key), "review-replies.json")
