import logging
import os
import subprocess

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
    def __init__(self, clone_url: str, clone_path: str, default_branch: str):
        self.clone_url = clone_url
        self.clone_path = clone_path
        self.default_branch = default_branch

    def ensure_repo_cloned(self):
        work_dir = os.path.dirname(self.clone_path)
        os.makedirs(work_dir, exist_ok=True)

        clone_url = _authed_url(self.clone_url)

        if os.path.isdir(os.path.join(self.clone_path, ".git")):
            log.info("Updating existing clone: %s", self.clone_path)
            self._update_remotes()
            _git(self.clone_path, "fetch", "origin")
            _git(self.clone_path, "checkout", self.default_branch)
            _git(self.clone_path, "reset", "--hard", f"origin/{self.default_branch}")
        else:
            log.info("Cloning %s -> %s", self.clone_url, self.clone_path)
            env = None
            if _gh_auth is not None:
                env = {**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
            subprocess.run(
                ["git", "clone", clone_url, self.clone_path],
                capture_output=True, text=True, timeout=600, check=True,
                env=env,
            )

    def _update_remotes(self):
        if _gh_auth is None:
            return
        origin_url = _authed_url(self.clone_url)
        _git(self.clone_path, "remote", "set-url", "origin", origin_url)

    def create_branch(self, branch: str):
        _git(self.clone_path, "checkout", self.default_branch)
        _git(self.clone_path, "checkout", "-b", branch)

    def checkout_branch(self, branch: str):
        self._update_remotes()
        _git(self.clone_path, "fetch", "origin")
        _git(self.clone_path, "checkout", branch)
        _git(self.clone_path, "pull", "origin", branch)

    def status(self, pathspec: str = "") -> str:
        args = ["status", "--porcelain"]
        if pathspec:
            args += ["--", pathspec]
        result = _git(self.clone_path, *args)
        return result.stdout.strip()

    def add(self, path: str = "."):
        if path == ".":
            _git(self.clone_path, "add", "-A")
        else:
            _git(self.clone_path, "add", path)

    def commit(self, message: str):
        _git(self.clone_path, "commit", "-m", message)

    def push_branch(self, branch: str, force: bool = False):
        self._update_remotes()
        args = ["push", "-u", "origin", branch]
        if force:
            args.append("--force-with-lease")
        result = _git(self.clone_path, *args, timeout=120)
        if result.returncode != 0:
            log.warning("Push failed: %s", result.stderr.strip())
            return False
        return True

    def remove_file(self, path: str):
        full_path = os.path.join(self.clone_path, path)
        if os.path.exists(full_path):
            os.remove(full_path)
