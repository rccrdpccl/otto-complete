import logging
import os
import signal
import threading

from otto_complete.config import load_config, RepoContext, SourceRepo
from otto_complete.logging_setup import setup_logging
from otto_complete.metrics import start_metrics_server
from otto_complete.clients.jira import JiraClient
from otto_complete.clients.github import GitHubClient
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.clients.git import GitClient
from otto_complete.clients.github_auth import GitHubAppAuth
from otto_complete.clients.auth import PatAuth
from otto_complete.budget import BudgetTracker
from otto_complete.claude_runner import set_budget_tracker
from otto_complete.bots.specifier import SpecifierBot
from otto_complete.bots.planner import PlannerBot
from otto_complete.bots.implementer import ImplementerBot

log = logging.getLogger(__name__)


def _build_auth(config, watcher):
    if watcher.auth_method == "github_app":
        if not config.github_app_id:
            log.warning("Watcher %s uses github_app auth but no GitHub App config found — "
                        "falling back to GITHUB_TOKEN env var", watcher.project)
            token = os.environ.get("GITHUB_TOKEN", "")
            return PatAuth(token) if token else None
        auth = GitHubAppAuth(
            app_id=config.github_app_id,
            private_key_path=config.github_app_private_key_path,
            installation_id=config.github_app_installation_id,
        )
        _ = auth.token
        log.info("GitHub App auth initialized for watcher %s (app_id=%s)",
                 watcher.project, config.github_app_id)
        auth.start_refresh_thread()
        return auth
    else:
        token = os.environ.get(watcher.token_env, "")
        if not token:
            raise ValueError(f"Watcher {watcher.project} requires env var {watcher.token_env} but it is empty")
        log.info("PAT auth initialized for watcher %s (env=%s)", watcher.project, watcher.token_env)
        return PatAuth(token)


def _build_source_auth(config, src_cfg):
    if src_cfg.auth_method == "github_app":
        if not config.github_app_id:
            token = os.environ.get("GITHUB_TOKEN", "")
            return PatAuth(token) if token else None
        auth = GitHubAppAuth(
            app_id=config.github_app_id,
            private_key_path=config.github_app_private_key_path,
            installation_id=config.github_app_installation_id,
        )
        _ = auth.token
        auth.start_refresh_thread()
        return auth
    else:
        token = os.environ.get(src_cfg.token_env, "")
        if not token:
            raise ValueError(
                f"Source repo {src_cfg.repo} requires env var "
                f"{src_cfg.token_env} but it is empty"
            )
        return PatAuth(token)


def main():
    setup_logging()
    log.info("=== otto-complete starting ===")

    config = load_config()
    start_metrics_server(port=9090)

    budget = BudgetTracker(
        max_budget=config.max_total_budget_usd,
        state_file=os.path.join(config.work_dir, ".budget.json"),
    )
    set_budget_tracker(budget)
    log.info("Global budget: $%.2f (spent so far: $%.2f)", budget.max_budget, budget.spent)

    jira = JiraClient(config)

    watcher_bots = []
    for watcher in config.watchers:
        auth = _build_auth(config, watcher)

        target_git = GitClient(config.clone_url, config.clone_path, config.default_branch, auth=auth)
        if watcher.platform == "gitlab":
            target_github = GitLabClient(config.repo, auth=auth, base_url=watcher.gitlab_url)
        else:
            target_github = GitHubClient(config.repo, auth=auth)
        target_ctx = RepoContext(
            repo=config.repo, clone_url=config.clone_url,
            clone_path=config.clone_path, default_branch=config.default_branch,
            specs_dir=config.specs_dir, git=target_git, github=target_github,
        )

        if watcher.workspace_repo:
            ws_repo_name = watcher.workspace_repo.rsplit("/", 1)[-1]
            ws_clone_path = os.path.join(config.work_dir, ws_repo_name)
            target_repo_name = config.repo.rsplit("/", 1)[-1]
            ws_specs_dir = f"{config.specs_dir}/{target_repo_name}"
            ws_default_branch = watcher.workspace_default_branch or config.default_branch

            ws_git = GitClient(watcher.workspace_clone_url, ws_clone_path, ws_default_branch, auth=auth)
            if watcher.platform == "gitlab":
                ws_github = GitLabClient(watcher.workspace_repo, auth=auth, base_url=watcher.gitlab_url)
            else:
                ws_github = GitHubClient(watcher.workspace_repo, auth=auth)
            spec_ctx = RepoContext(
                repo=watcher.workspace_repo, clone_url=watcher.workspace_clone_url,
                clone_path=ws_clone_path, default_branch=ws_default_branch,
                specs_dir=ws_specs_dir, git=ws_git, github=ws_github,
            )
            log.info("Watcher %s%s: workspace repo %s (specs at %s)",
                     watcher.project,
                     f"/{watcher.component}" if watcher.component else "",
                     watcher.workspace_repo, ws_specs_dir)
        else:
            spec_ctx = target_ctx

        source_repos = []
        for src_cfg in watcher.source_repos:
            src_auth = _build_source_auth(config, src_cfg)
            src_dir_name = src_cfg.repo.replace("/", "--")
            src_clone_path = os.path.join(config.work_dir, f"source-{src_dir_name}")
            src_branch = src_cfg.branch or "main"
            src_git = GitClient(src_cfg.clone_url, src_clone_path, src_branch, auth=src_auth)
            source_repos.append(SourceRepo(
                repo=src_cfg.repo, clone_path=src_clone_path,
                branch=src_branch, git=src_git,
            ))
        if source_repos:
            log.info("Watcher %s%s: %d source repo(s): %s",
                     watcher.project,
                     f"/{watcher.component}" if watcher.component else "",
                     len(source_repos),
                     ", ".join(s.repo for s in source_repos))

        watcher_bots.append((
            watcher,
            SpecifierBot(config, jira, spec_ctx, target_ctx, source_repos),
            PlannerBot(config, jira, spec_ctx, target_ctx, source_repos),
            ImplementerBot(config, jira, spec_ctx, target_ctx, source_repos),
        ))

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        log.info("Received signal %d, shutting down...", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("Polling loop started (interval=%ds, %d watchers)", config.poll_interval, len(config.watchers))

    while not shutdown.is_set():
        for watcher, specifier, planner, implementer in watcher_bots:
            if shutdown.is_set():
                break
            log.info("--- Pass: %s%s ---", watcher.project,
                     f"/{watcher.component}" if watcher.component else "")
            try:
                specifier.run_pass(watcher)
            except Exception:
                log.exception("Specifier pass failed for %s", watcher.project)
            try:
                planner.run_pass(watcher)
            except Exception:
                log.exception("Planner pass failed for %s", watcher.project)
            try:
                implementer.run_pass(watcher)
            except Exception:
                log.exception("Implementer pass failed for %s", watcher.project)

        if not shutdown.is_set():
            log.info("Sleeping %ds until next poll", config.poll_interval)
            shutdown.wait(timeout=config.poll_interval)

    log.info("=== otto-complete stopped ===")
