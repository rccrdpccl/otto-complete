# Phase 1: PAT Auth & Platform Abstraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PAT authentication support and introduce a `CodePlatform` protocol so bots are platform-agnostic, ready for GitLab in Phase 2.

**Architecture:** Define an `AuthProvider` protocol with two implementations (`GitHubAppAuth`, `PatAuth`). Define a `CodePlatform` protocol that `GitHubClient` implements. Replace global auth state with per-client dependency injection. Update config to support per-watcher `platform` and `auth` fields.

**Tech Stack:** Python 3.11+, `typing.Protocol`, dataclasses, PyYAML

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `otto_complete/clients/auth.py` | `AuthProvider` protocol + `PatAuth` class |
| Create | `otto_complete/clients/platform.py` | `CodePlatform` protocol definition |
| Modify | `otto_complete/clients/github_auth.py` | No code changes — already satisfies `AuthProvider` |
| Modify | `otto_complete/clients/git.py:1-30` | Remove global `_gh_auth` / `set_git_auth`, add `auth` param to `GitClient.__init__`, make `_git` and `_authed_url` instance methods |
| Modify | `otto_complete/clients/github.py:1-30` | Remove global `_gh_auth` / `set_gh_auth`, add `auth` param to `GitHubClient.__init__`, make `_run_gh` an instance method |
| Modify | `otto_complete/config.py` | Add `platform`, `auth_method`, `token_env`, `gitlab_url` to `Watcher`; update `RepoContext` to use `CodePlatform` type hint |
| Modify | `otto_complete/main.py:22-36,56-92` | Replace `_init_github_auth()` with per-watcher auth/client creation |
| Modify | `otto_complete/review.py:6,13,88,134,152,160` | Change type hints from `GitHubClient` to `CodePlatform` |
| Create | `tests/test_auth.py` | Tests for `PatAuth` |
| Create | `tests/test_config.py` | Tests for watcher config parsing |

---

### Task 1: Create AuthProvider Protocol and PatAuth

**Files:**
- Create: `otto_complete/clients/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write the test file for PatAuth**

```python
# tests/test_auth.py
from otto_complete.clients.auth import PatAuth


def test_pat_auth_returns_token():
    auth = PatAuth("ghp_abc123")
    assert auth.token == "ghp_abc123"


def test_pat_auth_returns_same_token_on_multiple_calls():
    auth = PatAuth("glpat-xyz789")
    assert auth.token == "glpat-xyz789"
    assert auth.token == "glpat-xyz789"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otto_complete.clients.auth'`

- [ ] **Step 3: Create auth.py with AuthProvider protocol and PatAuth**

```python
# otto_complete/clients/auth.py
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    @property
    def token(self) -> str: ...


class PatAuth:
    def __init__(self, token: str):
        self._token = token

    @property
    def token(self) -> str:
        return self._token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS — both tests green

- [ ] **Step 5: Add a test that GitHubAppAuth satisfies AuthProvider**

Add to `tests/test_auth.py`:

```python
from otto_complete.clients.auth import AuthProvider


def test_pat_auth_satisfies_protocol():
    auth = PatAuth("token")
    assert isinstance(auth, AuthProvider)
```

- [ ] **Step 6: Run all auth tests**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS — all three tests green

- [ ] **Step 7: Commit**

```bash
git add otto_complete/clients/auth.py tests/test_auth.py
git commit -m "add AuthProvider protocol and PatAuth implementation"
```

---

### Task 2: Create CodePlatform Protocol

**Files:**
- Create: `otto_complete/clients/platform.py`

This task defines the protocol that `GitHubClient` (and later `GitLabClient`) will implement. The method signatures are derived from the actual `GitHubClient` methods that bots use today. We keep the existing parameter types (`int` for PR numbers, `str` for labels) to minimize changes to `GitHubClient`.

- [ ] **Step 1: Create platform.py with CodePlatform protocol**

```python
# otto_complete/clients/platform.py
from __future__ import annotations

from typing import Protocol


class CodePlatform(Protocol):
    repo: str

    def create_pr(self, branch: str, title: str, body: str, base: str = "", labels: str = "") -> str: ...
    def pr_state(self, pr_number: int) -> str: ...
    def pr_is_merged(self, pr_number: int) -> bool: ...
    def find_pr_by_branch(self, branch: str) -> int | None: ...

    def get_review_threads(self, pr_number: int) -> dict: ...
    def get_pr_comments(self, pr_number: int) -> list[dict]: ...
    def reply_to_review_comment(self, pr_number: int, comment_id: int, body: str) -> bool: ...
    def comment_on_pr(self, pr_number: int, body: str) -> bool: ...
    def resolve_thread(self, thread_id: str) -> bool: ...
    def add_reaction(self, comment_id: int, reaction: str = "eyes") -> bool: ...
    def comment_has_reaction(self, comment_id: int, reaction: str = "eyes") -> bool: ...

    def get_pr_checks(self, pr_number: int) -> list[dict]: ...
    def get_failed_checks(self, pr_number: int) -> list[dict]: ...
    def checks_are_pending(self, pr_number: int) -> bool: ...
    def all_checks_pass(self, pr_number: int) -> bool: ...
    def format_failed_checks(self, failed_checks: list[dict]) -> str: ...
```

Note: These signatures exactly match the existing `GitHubClient` methods — `pr_number: int`, `labels: str` (comma-separated), return types. This means `GitHubClient` already satisfies this protocol with zero code changes to its method bodies.

- [ ] **Step 2: Verify GitHubClient satisfies CodePlatform structurally**

Run: `python -c "from otto_complete.clients.platform import CodePlatform; from otto_complete.clients.github import GitHubClient; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add otto_complete/clients/platform.py
git commit -m "add CodePlatform protocol for platform-agnostic bot operations"
```

---

### Task 3: Refactor GitClient to Use Dependency-Injected Auth

**Files:**
- Modify: `otto_complete/clients/git.py`

Currently `git.py` uses module-level `_gh_auth` global and `set_git_auth()`. Refactor so `GitClient.__init__` accepts an optional `auth` parameter, and `_git` / `_authed_url` become instance methods that use `self.auth`.

- [ ] **Step 1: Refactor git.py — remove globals, add auth to constructor**

Replace the entire content of `otto_complete/clients/git.py` with:

```python
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
        result = self._git(*args, timeout=120)
        if result.returncode != 0:
            log.warning("Push failed: %s", result.stderr.strip())
            return False
        return True

    def remove_file(self, path: str):
        full_path = os.path.join(self.clone_path, path)
        if os.path.exists(full_path):
            os.remove(full_path)
```

Key changes from the original:
- Removed `_gh_auth` global and `set_git_auth()` function
- `_git()` and `_authed_url()` are now instance methods using `self.auth`
- Constructor takes optional `auth: AuthProvider | None = None`
- `_authed_url()` handles both GitHub (`x-access-token`) and GitLab (`oauth2`) URL patterns

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from otto_complete.clients.git import GitClient; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify no references to removed symbols remain**

Run: `grep -rn "set_git_auth\|from.*git.*import.*set_git_auth" otto_complete/ --include="*.py"`
Expected: Only `main.py` (which we'll fix in Task 6)

- [ ] **Step 4: Commit**

```bash
git add otto_complete/clients/git.py
git commit -m "refactor GitClient to use injected auth instead of global state"
```

---

### Task 4: Refactor GitHubClient to Use Dependency-Injected Auth

**Files:**
- Modify: `otto_complete/clients/github.py`

Same pattern as Task 3: remove the `_gh_auth` global and `set_gh_auth()`, add `auth` to constructor, make `_run_gh` an instance method.

- [ ] **Step 1: Refactor github.py — remove globals, add auth to constructor**

Apply the following changes to `otto_complete/clients/github.py`:

**Remove** these lines (lines 10-16):
```python
_gh_auth = None


def set_gh_auth(auth):
    global _gh_auth
    _gh_auth = auth
```

**Replace** the `_run_gh` free function (lines 18-27) and `GitHubClient.__init__` (lines 30-31) with:

```python
class GitHubClient:
    def __init__(self, repo: str, auth=None):
        self.repo = repo
        self.auth = auth

    def _run_gh(self, *args, **kwargs) -> str:
        env = None
        if self.auth is not None:
            env = {**os.environ, "GH_TOKEN": self.auth.token}
        result = subprocess.run(
            ["gh", *args],
            capture_output=True, text=True, timeout=kwargs.get("timeout", 120),
            env=env,
        )
        return result.stdout.strip()
```

**In every method body**, replace `_run_gh(` with `self._run_gh(`:
- `create_pr` (lines 44, 48)
- `pr_state` (line 51)
- `find_pr_by_branch` (line 57-59)
- `get_review_threads` (line 90-95)
- `get_pr_comments` (line 100)
- `reply_to_review_comment` (line 106-108)
- `comment_on_pr` (line 118)
- `resolve_thread` (line 131)
- `add_reaction` (line 140-142)
- `comment_has_reaction` (line 151-153)
- `get_pr_checks` (line 160-163)

That's 14 call sites — every `_run_gh(` in the file becomes `self._run_gh(`.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from otto_complete.clients.github import GitHubClient, BOT_MARKER; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify no references to removed symbols remain elsewhere**

Run: `grep -rn "set_gh_auth\|from.*github.*import.*set_gh_auth" otto_complete/ --include="*.py"`
Expected: Only `main.py` (which we'll fix in Task 6)

- [ ] **Step 4: Commit**

```bash
git add otto_complete/clients/github.py
git commit -m "refactor GitHubClient to use injected auth instead of global state"
```

---

### Task 5: Update Watcher Config with Platform and Auth Fields

**Files:**
- Modify: `otto_complete/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write tests for watcher config parsing**

```python
# tests/test_config.py
import os
import tempfile
import yaml

from otto_complete.config import load_config


def _write_config(data: dict) -> str:
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def test_watcher_defaults_to_github_app():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "github_app_id": "123",
        "github_app_installation_id": "456",
        "watchers": [{"project": "PROJ"}],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "github_app"
        assert w.token_env == "GITHUB_TOKEN"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_pat_github():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "github",
            "auth": {"method": "pat", "token_env": "MY_GH_PAT"},
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "pat"
        assert w.token_env == "MY_GH_PAT"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_gitlab_defaults():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "gitlab",
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "gitlab"
        assert w.auth_method == "pat"
        assert w.token_env == "GITLAB_TOKEN"
        assert w.gitlab_url == "https://gitlab.com"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_gitlab_custom_url():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "gitlab",
            "gitlab_url": "https://gitlab.company.com",
            "auth": {"method": "pat", "token_env": "CORP_GL_TOKEN"},
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "gitlab"
        assert w.auth_method == "pat"
        assert w.token_env == "CORP_GL_TOKEN"
        assert w.gitlab_url == "https://gitlab.company.com"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_backward_compat_no_platform_no_auth():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "github_app_id": "123",
        "github_app_installation_id": "456",
        "watchers": [{"project": "PROJ"}],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "github_app"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `Watcher` has no `platform` attribute

- [ ] **Step 3: Update Watcher dataclass with new fields**

In `otto_complete/config.py`, update the `Watcher` dataclass:

```python
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
```

- [ ] **Step 4: Update load_config() to parse new watcher fields**

In `otto_complete/config.py`, update the watcher parsing in `load_config()`:

```python
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
        ))
```

- [ ] **Step 5: Update RepoContext type hint**

In `otto_complete/config.py`, change the `RepoContext` dataclass:

Replace the `TYPE_CHECKING` import block and `RepoContext`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from otto_complete.clients.git import GitClient
    from otto_complete.clients.platform import CodePlatform
```

And update `RepoContext`:

```python
@dataclass
class RepoContext:
    repo: str
    clone_url: str
    clone_path: str
    default_branch: str
    specs_dir: str
    git: GitClient
    github: CodePlatform
```

Note: We keep the field name `github` to avoid renaming it across all bot files in this phase. The type changes to `CodePlatform` but the name stays — renaming is cosmetic and can be done later.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS — all five tests green

- [ ] **Step 7: Commit**

```bash
git add otto_complete/config.py tests/test_config.py
git commit -m "add platform and auth config fields to Watcher dataclass"
```

---

### Task 6: Rewire main.py for Per-Watcher Auth and Client Creation

**Files:**
- Modify: `otto_complete/main.py`

This is the central wiring change. Replace `_init_github_auth()` with per-watcher auth/client creation.

- [ ] **Step 1: Update imports in main.py**

Replace:
```python
from otto_complete.clients.github import GitHubClient, set_gh_auth
from otto_complete.clients.git import GitClient, set_git_auth
from otto_complete.clients.github_auth import GitHubAppAuth
```

With:
```python
from otto_complete.clients.github import GitHubClient
from otto_complete.clients.git import GitClient
from otto_complete.clients.github_auth import GitHubAppAuth
from otto_complete.clients.auth import PatAuth
```

- [ ] **Step 2: Replace _init_github_auth with _build_auth helper**

Replace the `_init_github_auth` function (lines 22-36) with:

```python
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
```

- [ ] **Step 3: Remove the _init_github_auth(config) call from main()**

Delete line 45: `_init_github_auth(config)`

- [ ] **Step 4: Update the watcher loop to create per-watcher auth and clients**

Replace the watcher loop body (inside `for watcher in config.watchers:`) with:

```python
    watcher_bots = []
    for watcher in config.watchers:
        auth = _build_auth(config, watcher)

        target_git = GitClient(config.clone_url, config.clone_path, config.default_branch, auth=auth)
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

        watcher_bots.append((
            watcher,
            SpecifierBot(config, jira, spec_ctx, target_ctx),
            PlannerBot(config, jira, spec_ctx, target_ctx),
            ImplementerBot(config, jira, spec_ctx, target_ctx),
        ))
```

- [ ] **Step 5: Verify the module imports cleanly**

Run: `python -c "from otto_complete.main import main; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add otto_complete/main.py
git commit -m "wire up per-watcher auth and client creation in main loop"
```

---

### Task 7: Update review.py Type Hints

**Files:**
- Modify: `otto_complete/review.py`

The review module currently imports `GitHubClient` for type hints. Update to use `CodePlatform`.

- [ ] **Step 1: Update imports and type hints**

In `otto_complete/review.py`, replace:

```python
from otto_complete.clients.github import GitHubClient, BOT_MARKER
```

With:

```python
from otto_complete.clients.github import BOT_MARKER
from otto_complete.clients.platform import CodePlatform
```

Then replace every `GitHubClient` type hint with `CodePlatform`:

- Line 13: `def collect_unaddressed_comments(github: GitHubClient, ...)` → `def collect_unaddressed_comments(github: CodePlatform, ...)`
- Line 88: `def post_review_replies(github: GitHubClient, ...)` → `def post_review_replies(github: CodePlatform, ...)`
- Line 134: `def auto_resolve_review_threads(github: GitHubClient, ...)` → `def auto_resolve_review_threads(github: CodePlatform, ...)`
- Line 152: `def mark_issue_comments_seen(github: GitHubClient, ...)` → `def mark_issue_comments_seen(github: CodePlatform, ...)`
- Line 160: `def _post_fallback_replies(github: GitHubClient, ...)` → `def _post_fallback_replies(github: CodePlatform, ...)`

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from otto_complete.review import collect_unaddressed_comments; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add otto_complete/review.py
git commit -m "update review.py type hints from GitHubClient to CodePlatform"
```

---

### Task 8: Verify End-to-End Import Chain

**Files:** None — verification only

- [ ] **Step 1: Verify all modules import without error**

Run:

```bash
python -c "
from otto_complete.clients.auth import AuthProvider, PatAuth
from otto_complete.clients.platform import CodePlatform
from otto_complete.clients.github_auth import GitHubAppAuth
from otto_complete.clients.git import GitClient
from otto_complete.clients.github import GitHubClient
from otto_complete.config import Config, Watcher, RepoContext, load_config
from otto_complete.review import collect_unaddressed_comments
from otto_complete.bots.base import BaseBot
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Verify no remaining references to removed globals**

Run:

```bash
grep -rn "set_gh_auth\|set_git_auth\|_gh_auth" otto_complete/ --include="*.py"
```

Expected: No output (all references removed)

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit (if any cleanup was needed)**

```bash
git add -A
git commit -m "verify end-to-end import chain and cleanup"
```
