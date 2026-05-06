import logging
import os
import subprocess

from otto_complete.config import Config

log = logging.getLogger(__name__)

_gh_auth = None


def set_git_auth(auth):
    global _gh_auth
    _gh_auth = auth


def _git(clone_path: str, *args, **kwargs) -> subprocess.CompletedProcess:
    env = None
    if _gh_auth is not None:
        env = {**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", "-C", clone_path, *args],
        capture_output=True, text=True, timeout=kwargs.get("timeout", 300),
        env=env,
    )


def _authed_url(url: str) -> str:
    if _gh_auth is not None and url.startswith("https://github.com/"):
        token = _gh_auth.token
        return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
    return url


class GitClient:
    def __init__(self, config: Config):
        self.config = config

    def ensure_repo_cloned(self):
        cfg = self.config
        os.makedirs(cfg.work_dir, exist_ok=True)

        clone_url = _authed_url(cfg.clone_url)

        if os.path.isdir(os.path.join(cfg.clone_path, ".git")):
            log.info("Updating existing clone: %s", cfg.clone_path)
            self._update_remotes()
            _git(cfg.clone_path, "fetch", "origin")
            _git(cfg.clone_path, "checkout", cfg.default_branch)
            _git(cfg.clone_path, "reset", "--hard", f"origin/{cfg.default_branch}")
        else:
            log.info("Cloning %s -> %s", cfg.clone_url, cfg.clone_path)
            env = None
            if _gh_auth is not None:
                env = {**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
            subprocess.run(
                ["git", "clone", clone_url, cfg.clone_path],
                capture_output=True, text=True, timeout=600, check=True,
                env=env,
            )

    def _update_remotes(self):
        cfg = self.config
        if _gh_auth is None:
            return
        origin_url = _authed_url(cfg.clone_url)
        _git(cfg.clone_path, "remote", "set-url", "origin", origin_url)

    def create_branch(self, branch: str):
        cfg = self.config
        _git(cfg.clone_path, "checkout", cfg.default_branch)
        _git(cfg.clone_path, "checkout", "-b", branch)

    def checkout_branch(self, branch: str):
        cfg = self.config
        self._update_remotes()
        _git(cfg.clone_path, "fetch", "origin")
        _git(cfg.clone_path, "checkout", branch)
        _git(cfg.clone_path, "pull", "origin", branch)

    def status(self, pathspec: str = "") -> str:
        args = ["status", "--porcelain"]
        if pathspec:
            args += ["--", pathspec]
        result = _git(self.config.clone_path, *args)
        return result.stdout.strip()

    def add(self, path: str = "."):
        if path == ".":
            _git(self.config.clone_path, "add", "-A")
        else:
            _git(self.config.clone_path, "add", path)

    def commit(self, message: str):
        _git(self.config.clone_path, "commit", "-m", message)

    def push_branch(self, branch: str, force: bool = False):
        cfg = self.config
        self._update_remotes()
        args = ["push", "-u", "origin", branch]
        if force:
            args.append("--force-with-lease")
        result = _git(cfg.clone_path, *args, timeout=120)
        if result.returncode != 0:
            log.warning("Push failed: %s", result.stderr.strip())
            return False
        return True

    def remove_file(self, path: str):
        full_path = os.path.join(self.config.clone_path, path)
        if os.path.exists(full_path):
            os.remove(full_path)
