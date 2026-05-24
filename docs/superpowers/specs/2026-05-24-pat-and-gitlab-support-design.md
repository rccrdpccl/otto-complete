# PAT Authentication & GitLab Platform Support

## Summary

Add Personal Access Token (PAT) authentication as a first-class auth method alongside GitHub App auth, and add full GitLab platform support (MRs, CI checks, reviews) behind a `CodePlatform` protocol interface. Delivered in two phases. JIRA remains the sole issue tracker; the platform choice only affects where code and PRs/MRs live.

## Architecture: Protocol Interface

A `CodePlatform` protocol defines the contract that both `GitHubClient` and `GitLabClient` implement. Bots interact with the protocol, never with a specific platform. Each watcher gets its own platform client based on its config.

```
Bot → CodePlatform (protocol) → GitHubClient (gh CLI, unchanged internals)
                               → GitLabClient (HTTP requests via requests library)
```

## Auth Abstraction

### AuthProvider Protocol

```python
class AuthProvider(Protocol):
    @property
    def token(self) -> str: ...
```

### Implementations

- **GitHubAppAuth** (existing): Already has a `.token` property. Satisfies the protocol with no code changes — just add the type annotation.
- **PatAuth** (new): Trivial class. Takes a token string at init, returns it from `.token`. Works for both GitHub and GitLab PATs.

### Dependency Injection

The current global `set_gh_auth()` / `set_git_auth()` pattern is removed. Instead, each client receives its `AuthProvider` at construction time. This allows multiple watchers to use different auth methods simultaneously.

## Configuration

Each watcher entry gains two optional fields — `platform` and `auth`:

```yaml
watchers:
  - repo: "org/my-repo"
    jira_project: "MGMT"
    jira_label: "auto-spec"
    platform: github          # "github" (default) or "gitlab"
    auth:
      method: pat             # "pat" or "github_app" (default for github)
      token_env: MY_PAT_VAR   # env var holding the PAT (default: GITHUB_TOKEN or GITLAB_TOKEN)

  - repo: "org/other-repo"
    platform: gitlab
    gitlab_url: https://gitlab.company.com  # optional, defaults to https://gitlab.com
    auth:
      method: pat
      token_env: GITLAB_TOKEN
```

### Defaults and Backward Compatibility

- `platform` defaults to `"github"`
- `auth.method` defaults to `"github_app"` for GitHub watchers, `"pat"` for GitLab watchers
- `auth.token_env` defaults to `GITHUB_TOKEN` (GitHub) or `GITLAB_TOKEN` (GitLab)
- Top-level `github_app_*` fields remain — used when a watcher specifies `auth.method: github_app`
- A config with no `platform` or `auth` block behaves identically to today

## CodePlatform Protocol

```python
class CodePlatform(Protocol):
    # PR/MR lifecycle
    def create_pr(self, repo: str, head: str, base: str, title: str, body: str, labels: list[str]) -> str: ...
    def pr_state(self, repo: str, pr_id: str) -> str: ...
    def pr_is_merged(self, repo: str, pr_id: str) -> bool: ...
    def find_pr_by_branch(self, repo: str, branch: str) -> str | None: ...

    # Reviews
    def get_review_threads(self, repo: str, pr_id: str) -> list[dict]: ...
    def get_pr_comments(self, repo: str, pr_id: str) -> list[dict]: ...
    def reply_to_review_comment(self, repo: str, pr_id: str, comment_id: str, body: str) -> None: ...
    def comment_on_pr(self, repo: str, pr_id: str, body: str) -> None: ...
    def resolve_thread(self, repo: str, pr_id: str, thread_id: str) -> None: ...
    def add_reaction(self, repo: str, comment_id: str, reaction: str) -> None: ...

    # CI
    def get_pr_checks(self, repo: str, pr_id: str) -> list[dict]: ...
```

### Client Implementations

- **GitHubClient**: Refactored from existing `github.py`. Keeps `gh` CLI internally. Methods already match the protocol — changes are constructor signature (takes `AuthProvider`) and type annotations.
- **GitLabClient** (Phase 2): Uses `requests` to call GitLab REST API v4. Maps GitLab concepts to the common interface:
  - Merge Requests → PR lifecycle methods
  - Pipelines → CI checks
  - Discussions → review threads
  - Award Emoji → reactions

### Bot Marker

Both platform clients must support `BOT_MARKER` (`<!-- otto-complete -->`) to identify bot-authored comments and prevent self-replies. The marker is appended to comment bodies and checked when filtering incoming comments. GitLab uses the same HTML comment syntax in Markdown, so the existing marker works on both platforms.

### GitClient

Stays mostly as-is. Changes:
- Constructor takes `AuthProvider` instead of using global state
- `_authed_url()` already handles HTTPS token injection — works for both GitHub and GitLab URL patterns (`https://oauth2:{token}@gitlab.com/...` for GitLab, `https://x-access-token:{token}@github.com/...` for GitHub)

## Wiring (main.py)

Per-watcher initialization replaces the global `_init_github_auth()`:

```python
for watcher_cfg in config.watchers:
    # 1. Build auth provider
    if watcher_cfg.auth_method == "github_app":
        auth = GitHubAppAuth(
            app_id=config.github_app_id,
            private_key_path=config.github_app_private_key_path,
            installation_id=config.github_app_installation_id,
        )
        auth.start_refresh_thread()
    else:  # pat
        token = os.environ[watcher_cfg.token_env]
        auth = PatAuth(token)

    # 2. Build git client
    git_client = GitClient(auth=auth)

    # 3. Build platform client
    if watcher_cfg.platform == "github":
        platform = GitHubClient(auth=auth)
    elif watcher_cfg.platform == "gitlab":
        platform = GitLabClient(auth=auth, base_url=watcher_cfg.gitlab_url)

    # 4. Pass to bots
    bots = create_bots(git=git_client, platform=platform, ...)
```

## Phasing

### Phase 1 — Auth Abstraction + PAT + Git Ops

Scope:
- `AuthProvider` protocol + `PatAuth` class
- Type-annotate `GitHubAppAuth` to satisfy `AuthProvider`
- Refactor `GitClient` to take `AuthProvider` at construction, remove global state
- Refactor `GitHubClient` to take `AuthProvider` at construction, remove global state
- Per-watcher config parsing (`platform`, `auth` block)
- Per-watcher client creation in `main.py`
- Remove `set_gh_auth()` / `set_git_auth()` global setters
- Define `CodePlatform` protocol (only `GitHubClient` implements it)
- Bots type-annotated to accept `CodePlatform` instead of `GitHubClient`

Delivers: PAT auth works for GitHub watchers. Architecture is ready for Phase 2. Config accepts `platform: gitlab` but `GitLabClient` doesn't exist yet (startup error if used).

### Phase 2 — GitLab API Client

Scope:
- `GitLabClient` implementing `CodePlatform` via HTTP requests
- GitLab MR creation, state checks, merge detection
- GitLab Discussions → review thread mapping
- GitLab Pipelines → CI checks mapping
- GitLab award emoji → reactions
- `gitlab_url` support for self-hosted instances
- Prompt template adjustments ("pull request" → "merge request" in user-facing text where appropriate)

Delivers: Full GitLab parity. A watcher can target a GitLab repo and the full spec → plan → implement pipeline works end-to-end.
