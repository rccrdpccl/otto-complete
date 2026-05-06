import logging
import signal
import threading

from otto_complete.config import load_config
from otto_complete.logging_setup import setup_logging
from otto_complete.metrics import start_metrics_server
from otto_complete.clients.jira import JiraClient
from otto_complete.clients.github import GitHubClient, set_gh_auth
from otto_complete.clients.git import GitClient, set_git_auth
from otto_complete.clients.github_auth import GitHubAppAuth
from otto_complete.budget import BudgetTracker
from otto_complete.claude_runner import set_budget_tracker
from otto_complete.bots.specifier import SpecifierBot
from otto_complete.bots.planner import PlannerBot
from otto_complete.bots.implementer import ImplementerBot

log = logging.getLogger(__name__)


def _init_github_auth(config):
    if not config.github_app_id:
        log.info("No GitHub App config — using GITHUB_TOKEN from env")
        return
    auth = GitHubAppAuth(
        app_id=config.github_app_id,
        private_key_path=config.github_app_private_key_path,
        installation_id=config.github_app_installation_id,
    )
    _ = auth.token
    log.info("GitHub App auth initialized (app_id=%s, installation=%s)",
             config.github_app_id, config.github_app_installation_id)
    set_gh_auth(auth)
    set_git_auth(auth)
    auth.start_refresh_thread()


def main():
    setup_logging()
    log.info("=== otto-complete starting ===")

    config = load_config()
    start_metrics_server(port=9090)
    _init_github_auth(config)

    import os
    budget = BudgetTracker(
        max_budget=config.max_total_budget_usd,
        state_file=os.path.join(config.work_dir, ".budget.json"),
    )
    set_budget_tracker(budget)
    log.info("Global budget: $%.2f (spent so far: $%.2f)", budget.max_budget, budget.spent)

    jira = JiraClient(config)
    github = GitHubClient(config)
    git = GitClient(config)

    specifier = SpecifierBot(config, jira, github, git)
    planner = PlannerBot(config, jira, github, git)
    implementer = ImplementerBot(config, jira, github, git)

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        log.info("Received signal %d, shutting down...", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("Polling loop started (interval=%ds, %d watchers)", config.poll_interval, len(config.watchers))

    while not shutdown.is_set():
        for watcher in config.watchers:
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
