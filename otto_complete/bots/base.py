import logging
import os

from otto_complete.config import Config, Watcher
from otto_complete.clients.jira import JiraClient
from otto_complete.clients.github import GitHubClient
from otto_complete.clients.git import GitClient
from otto_complete.claude_runner import run_claude

log = logging.getLogger(__name__)

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.normpath(os.path.join(_PACKAGE_ROOT, "..", "templates"))


class BaseBot:
    name = "base"

    def __init__(self, config: Config, jira: JiraClient, github: GitHubClient, git: GitClient):
        self.config = config
        self.jira = jira
        self.github = github
        self.git = git

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
    ) -> int:
        exit_code, _ = run_claude(self.config, bot_name, issue_key, prompt, tools, max_turns, max_budget)
        return exit_code

    def commit_and_push(self, branch: str, message: str, force: bool = False, pathspec: str = "") -> bool:
        changes = self.git.status(pathspec)
        if not changes:
            return False
        if pathspec:
            self.git.add(pathspec)
        else:
            self.git.add()
        self.git.commit(message)
        return self.git.push_branch(branch, force=force)

    def spec_dir(self, issue_key: str) -> str:
        return os.path.join(self.config.clone_path, self.config.specs_dir, issue_key)

    def replies_file(self, issue_key: str) -> str:
        return os.path.join(self.spec_dir(issue_key), "review-replies.json")
