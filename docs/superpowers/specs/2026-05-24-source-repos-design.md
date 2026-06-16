# Source Repos per Watcher

## Overview

Add support for read-only source repositories per watcher. When implementing features in a target repo (e.g., integration tests), bots often need to reference code in other repositories (e.g., the feature source code). This design introduces a `source_repos` list on each watcher, where each source repo has its own platform, auth, and branch configuration.

## Requirements

1. Each watcher can declare zero or more source repos in config.
2. Source repos are read-only — cloned and updated for reference, never modified.
3. Each source repo has independent platform (GitHub/GitLab), auth (PAT/GitHub App), and branch config.
4. All three bots (Specifier, Planner, Implementer) receive source repo paths and pass them to Claude via prompt templates.
5. Fully backward compatible — no source repos configured means no behavior change.

## Config Model

### New dataclass: `SourceRepoConfig`

Added to `config.py`:

```python
@dataclass
class SourceRepoConfig:
    repo: str                  # "org/repo-name"
    clone_url: str             # HTTPS clone URL
    branch: str = ""           # defaults to "main" if empty
    platform: str = "github"   # "github" or "gitlab"
    auth_method: str = "pat"   # "github_app" or "pat"
    token_env: str = ""        # env var holding PAT
    gitlab_url: str = ""       # GitLab base URL if platform is gitlab
```

### Watcher extension

```python
@dataclass
class Watcher:
    # ... existing fields ...
    source_repos: list[SourceRepoConfig] = field(default_factory=list)
```

### YAML config example

```yaml
watchers:
  - project: QE
    platform: github
    auth:
      method: github_app
    source_repos:
      - repo: myorg/feature-service
        clone_url: https://github.com/myorg/feature-service.git
        branch: main
        platform: github
        auth:
          method: pat
          token_env: FEATURE_SVC_TOKEN
      - repo: myorg/shared-lib
        clone_url: https://gitlab.com/myorg/shared-lib.git
        platform: gitlab
        gitlab_url: https://gitlab.com
        auth:
          method: pat
          token_env: GITLAB_SHARED_LIB_TOKEN
```

### Config parsing

`load_config()` parses `source_repos` from each watcher's YAML block. Each source repo's `auth` block follows the same `method`/`token_env` pattern as the watcher's own `auth` block. Default `auth_method` is `"pat"` (most source repos will use PATs). Default `token_env` follows platform convention: `"GITHUB_TOKEN"` for GitHub, `"GITLAB_TOKEN"` for GitLab.

## Runtime Data Model

### New dataclass: `SourceRepo`

Added to `config.py`:

```python
@dataclass
class SourceRepo:
    repo: str           # "org/repo-name"
    clone_path: str     # absolute path to clone on disk
    branch: str         # branch that was checked out
    git: GitClient      # for clone/update operations
```

No `CodePlatform` client — read-only repos don't need PR, comment, or CI operations.

### Clone path naming

Source repos use `source-{org}--{repo}` directory names to avoid collisions:

```python
src_dir_name = src_cfg.repo.replace("/", "--")
src_clone_path = os.path.join(config.work_dir, f"source-{src_dir_name}")
```

Example: `myorg/feature-service` clones to `/tmp/ai-agent/source-myorg--feature-service`.

Target and workspace repos keep their existing naming for backward compatibility.

## Wiring in `main.py`

### Building source repos

For each watcher, after building target and workspace contexts:

```python
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
```

### Auth function

New `_build_source_auth(config, src_cfg)` mirrors `_build_auth` but reads from `SourceRepoConfig`:

- **PAT auth**: Reads token from `src_cfg.token_env` env var. Raises `ValueError` if empty.
- **GitHub App auth**: Reuses global GitHub App config (`config.github_app_id`, `config.github_app_private_key_path`, `config.github_app_installation_id`). Falls back to `GITHUB_TOKEN` env var if no app config.
- **GitLab source repos**: Always PAT auth. `GitClient` handles GitLab URL token injection via `_authed_url()`.

### Passing to bots

All three bot constructors receive the `source_repos` list:

```python
SpecifierBot(config, jira, spec_ctx, target_ctx, source_repos),
PlannerBot(config, jira, spec_ctx, target_ctx, source_repos),
ImplementerBot(config, jira, spec_ctx, target_ctx, source_repos),
```

## BaseBot Changes

### Constructor

```python
def __init__(self, config, jira, spec_ctx, impl_ctx, source_repos=None):
    ...
    self.source_repos: list[SourceRepo] = source_repos or []
```

### New helper: `ensure_source_repos_cloned()`

```python
def ensure_source_repos_cloned(self):
    for src in self.source_repos:
        src.git.ensure_repo_cloned()
```

Called by each bot before invoking Claude, alongside existing `spec_ctx.git.ensure_repo_cloned()` and `impl_ctx.git.ensure_repo_cloned()` calls.

### New helper: `format_source_repos_section()`

```python
def format_source_repos_section(self) -> str:
    if not self.source_repos:
        return ""
    lines = [
        "## Source Repositories (Read-Only Reference)\n",
        "The following repositories are cloned locally for reference. "
        "Read their code to understand the source implementations, "
        "but do NOT modify them.\n",
    ]
    for src in self.source_repos:
        lines.append(f"- **{src.repo}** (branch: {src.branch}): {src.clone_path}")
    return "\n".join(lines)
```

Returns empty string when no source repos are configured — no change to existing prompt output.

## Prompt Template Changes

All 7 templates get a `{{SOURCE_REPOS}}` placeholder:

| Template | Placement |
|---|---|
| `spec-prompt.md` | After the JIRA issue section, before Instructions |
| `plan-prompt.md` | After the spec reference, before Instructions |
| `implement-prompt.md` | After the spec/plan references, before Repository Conventions |
| `ci-fix-prompt.md` | After context section |
| `impl-review-prompt.md` | After context section |
| `spec-review-prompt.md` | After context section |
| `plan-review-prompt.md` | After context section |

Each bot passes `SOURCE_REPOS=self.format_source_repos_section()` to `render_template()`.

When source repos are configured, the rendered section looks like:

```
## Source Repositories (Read-Only Reference)

The following repositories are cloned locally for reference. Read their code to understand the source implementations, but do NOT modify them.

- **myorg/feature-service** (branch: main): /tmp/ai-agent/source-myorg--feature-service
- **myorg/shared-lib** (branch: release/v2): /tmp/ai-agent/source-myorg--shared-lib
```

## What Does NOT Change

- `GitClient` — already repo-agnostic, no modifications needed
- `CodePlatform` / `GitHubClient` / `GitLabClient` — source repos don't need platform clients
- `RepoContext` — used for target and workspace repos only
- `claude_runner.py` — Claude runs in target repo's `cwd`; source repos are accessed via absolute paths in the prompt
- `review.py` — review handling operates on target repo PRs only
- `budget.py` / metrics — no changes
- Kubernetes deployment — only new env vars for source repo tokens need to be added to Secrets

## Backward Compatibility

- `source_repos` defaults to empty list — existing configs work unchanged
- `BaseBot` constructor defaults `source_repos=None` — existing instantiations work
- Templates render `{{SOURCE_REPOS}}` as empty string when no source repos configured
- No changes to existing `Watcher`, `Config`, or `RepoContext` field semantics
