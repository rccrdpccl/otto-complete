from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from otto_complete.clients.git import GitClient
    from otto_complete.clients.platform import CodePlatform


@dataclass
class SourceRepoConfig:
    repo: str
    clone_url: str
    branch: str = ""
    platform: str = "github"
    auth_method: str = "pat"
    token_env: str = ""
    gitlab_url: str = ""
    description: str = ""


@dataclass
class SourceRepo:
    repo: str
    clone_path: str
    branch: str
    git: GitClient
    description: str = ""


@dataclass
class Watcher:
    project: str
    component: str = ""
    workspace_repo: str = ""
    workspace_clone_url: str = ""
    workspace_default_branch: str = ""
    platform: str = "github"
    auth_method: str = ""
    token_env: str = ""
    gitlab_url: str = ""
    source_repos: list[SourceRepoConfig] = field(default_factory=list)


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


@dataclass
class RepoContext:
    repo: str
    clone_url: str
    clone_path: str
    default_branch: str
    specs_dir: str
    git: GitClient
    github: CodePlatform


def load_config() -> Config:
    config_path = os.environ.get("OTTO_CONFIG", "/etc/otto-complete/config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    watchers = []
    for w in raw.pop("watchers", []):
        auth_block = w.get("auth", {})
        platform = w.get("platform", "github")

        if platform == "gitlab":
            default_method = "pat"
            default_token_env = "GITLAB_TOKEN"
            default_gitlab_url = "https://gitlab.com"
        else:
            default_method = "github_app"
            default_token_env = "GITHUB_TOKEN"
            default_gitlab_url = ""

        source_repo_configs = []
        for src in w.get("source_repos", []):
            src_auth = src.get("auth", {})
            src_platform = src.get("platform", "github")
            if src_platform == "gitlab":
                src_default_token = "GITLAB_TOKEN"
                src_default_gitlab_url = "https://gitlab.com"
            else:
                src_default_token = "GITHUB_TOKEN"
                src_default_gitlab_url = ""
            source_repo_configs.append(SourceRepoConfig(
                repo=src["repo"],
                clone_url=src["clone_url"],
                branch=src.get("branch", ""),
                platform=src_platform,
                auth_method=src_auth.get("method", "pat"),
                token_env=src_auth.get("token_env", src_default_token),
                gitlab_url=src.get("gitlab_url", src_default_gitlab_url),
                description=src.get("description", ""),
            ))

        watchers.append(Watcher(
            project=w["project"],
            component=w.get("component", ""),
            workspace_repo=w.get("workspace_repo", ""),
            workspace_clone_url=w.get("workspace_clone_url", ""),
            workspace_default_branch=w.get("workspace_default_branch", ""),
            platform=platform,
            auth_method=auth_block.get("method", default_method),
            token_env=auth_block.get("token_env", default_token_env),
            gitlab_url=w.get("gitlab_url", default_gitlab_url),
            source_repos=source_repo_configs,
        ))

    known_fields = {f.name for f in Config.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in known_fields}

    return Config(watchers=watchers, **filtered)
