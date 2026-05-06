import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Watcher:
    project: str
    component: str = ""


@dataclass
class Config:
    repo: str
    clone_url: str
    label: str = "auto-plan"
    specs_dir: str = "specs"
    branch_prefix_spec: str = "spec/"
    branch_prefix_plan: str = "plan/"
    branch_prefix_impl: str = "impl/"
    default_branch: str = "master"
    max_total_budget_usd: float = 50.0
    poll_interval: int = 120

    max_turns_spec: int = 15
    max_turns_plan: int = 20
    max_turns_impl: int = 50
    max_turns_review: int = 20
    max_turns_ci_fix: int = 30

    max_budget_spec: str = "1.00"
    max_budget_plan: str = "2.00"
    max_budget_impl: str = "10.00"
    max_budget_review: str = "2.00"
    max_budget_ci_fix: str = "5.00"

    ci_max_retries: int = 3

    watchers: list[Watcher] = field(default_factory=list)

    work_dir: str = ""
    repo_name: str = ""
    clone_path: str = ""

    jira_url: str = ""
    jira_user: str = ""
    jira_api_token: str = ""

    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_app_installation_id: str = ""

    def __post_init__(self):
        self.work_dir = self.work_dir or os.environ.get("OTTO_WORK_DIR", "/tmp/ai-agent")
        self.repo_name = self.repo.rsplit("/", 1)[-1] if self.repo else ""
        self.clone_path = os.path.join(self.work_dir, self.repo_name)

        self.jira_url = os.environ.get("JIRA_URL", "")
        self.jira_user = os.environ.get("JIRA_USER", "")
        self.jira_api_token = os.environ.get("JIRA_API_TOKEN", "")

        self.github_app_private_key_path = (
            self.github_app_private_key_path
            or os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "")
        )


def load_config() -> Config:
    config_path = os.environ.get("OTTO_CONFIG", "/etc/otto-complete/config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    watchers = [
        Watcher(project=w["project"], component=w.get("component", ""))
        for w in raw.pop("watchers", [])
    ]

    known_fields = {f.name for f in Config.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in known_fields}

    return Config(watchers=watchers, **filtered)
