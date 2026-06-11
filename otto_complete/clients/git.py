import logging
import os
import subprocess

from otto_complete.clients.auth import AuthProvider

log = logging.getLogger(__name__)


class GitClient:
    def __init__(self, clone_url: str, clone_path: str, default_branch: str,
                 auth: AuthProvider | None = None):
        self.clone_url = clone_url
        self.clone_path = clone_path
        self.default_branch = default_branch
        self.auth = auth

    def _git(self, *args, **kwargs) -> subprocess.CompletedProcess:
        env = None
        if self.auth is not None:
            env = {**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
        return subprocess.run(
            ["git", "-C", self.clone_path, *args],
            capture_output=True, text=True, timeout=kwargs.get("timeout", 300),
            env=env,
        )

    def _authed_url(self, url: str) -> str:
        if self.auth is None:
            return url
        token = self.auth.token
        if url.startswith("https://github.com/"):
            return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
        if url.startswith("https://gitlab.com/") or "gitlab" in url:
            host = url.split("://", 1)[1].split("/", 1)[0]
            return url.replace(f"https://{host}/", f"https://oauth2:{token}@{host}/")
        return url

    def ensure_repo_cloned(self):
        work_dir = os.path.dirname(self.clone_path)
        os.makedirs(work_dir, exist_ok=True)

        clone_url = self._authed_url(self.clone_url)

        if os.path.isdir(os.path.join(self.clone_path, ".git")):
            log.info("Updating existing clone: %s", self.clone_path)
            self._update_remotes()
            self._git("fetch", "origin")
            self._git("checkout", self.default_branch)
            self._git("reset", "--hard", f"origin/{self.default_branch}")
        else:
            log.info("Cloning %s -> %s", self.clone_url, self.clone_path)
            env = None
            if self.auth is not None:
                env = {**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
            subprocess.run(
                ["git", "clone", clone_url, self.clone_path],
                capture_output=True, text=True, timeout=600, check=True,
                env=env,
            )

    def _update_remotes(self):
        if self.auth is None:
            return
        origin_url = self._authed_url(self.clone_url)
        self._git("remote", "set-url", "origin", origin_url)

    def create_branch(self, branch: str):
        self._git("checkout", self.default_branch)
        self._git("checkout", "-b", branch)

    def checkout_branch(self, branch: str):
        self._update_remotes()
        self._git("fetch", "origin")
        self._git("checkout", branch)
        self._git("pull", "origin", branch)

    def status(self, pathspec: str = "") -> str:
        args = ["status", "--porcelain"]
        if pathspec:
            args += ["--", pathspec]
        result = self._git(*args)
        return result.stdout.strip()

    def add(self, path: str = "."):
        if path == ".":
            self._git("add", "-A")
        else:
            self._git("add", path)

    def commit(self, message: str):
        self._git("commit", "-m", message)

    def push_branch(self, branch: str, force: bool = False):
        self._update_remotes()
        args = ["push", "-u", "origin", branch]
        if force:
            args.append("--force-with-lease")
        try:
            result = self._git(*args, timeout=120)
        except subprocess.TimeoutExpired:
            log.warning("Push timed out for branch %s", branch)
            return False
        if result.returncode != 0:
            log.warning("Push failed: %s", result.stderr.strip())
            return False
        return True

    def has_commits_ahead(self, branch: str) -> bool:
        result = self._git("rev-list", "--count", f"{self.default_branch}..{branch}")
        return int(result.stdout.strip()) > 0

    def remove_file(self, path: str):
        full_path = os.path.join(self.clone_path, path)
        if os.path.exists(full_path):
            os.remove(full_path)
