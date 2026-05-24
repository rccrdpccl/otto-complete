# Workspace Repo: Separate Spec/Plan Repo from Target Repo

## Problem

otto-complete assumes full control of the target repo — spec, plan, and implementation artifacts all live in the same repository. When the target repo is owned by another team/org, we can only push code changes (implementation phase), not spec/plan files. We need a way to use a separate "workspace" repo we own for the spec and plan phases while still targeting an external repo for implementation.

## Design

### Overview

Introduce a `RepoContext` abstraction that bundles a repo's identity with its git and GitHub clients. Each watcher can optionally specify a workspace repo. When configured, the specifier and planner bots operate on the workspace repo, while the implementer bot operates on the target repo for code changes but reads spec/plan files from the workspace repo clone.

When no workspace is configured, both contexts point to the same repo — fully backward compatible.

### Config Changes

`Watcher` gets three optional fields:

```python
@dataclass
class Watcher:
    project: str
    component: str = ""
    workspace_repo: str = ""              # e.g. "myorg/otto-specs"
    workspace_clone_url: str = ""         # e.g. "https://github.com/myorg/otto-specs.git"
    workspace_default_branch: str = ""    # e.g. "main"; falls back to config.default_branch
```

Example YAML:

```yaml
repo: "theirorg/their-repo"
clone_url: "https://github.com/theirorg/their-repo.git"
default_branch: master
watchers:
  - project: MGMT
    component: backend
    workspace_repo: "myorg/otto-specs"
    workspace_clone_url: "https://github.com/myorg/otto-specs.git"
    workspace_default_branch: "main"
  - project: INTERNAL
    # no workspace — existing behavior
```

### RepoContext Dataclass

Defined in `config.py` alongside `Watcher` and `Config`:

```python
@dataclass
class RepoContext:
    repo: str            # "org/repo-name"
    clone_url: str
    clone_path: str
    default_branch: str
    specs_dir: str       # path within this repo for spec/plan files
    git: GitClient
    github: GitHubClient
```

When workspace is configured, the workspace context's `specs_dir` is `specs/{target-repo-name}` to namespace by target repo and avoid collisions in the shared workspace repo. File layout within the workspace repo:

```
specs/
  their-repo/
    MGMT-1234/
      spec.md
      plan.md
      tasks.md
    MGMT-5678/
      spec.md
      ...
```

### GitClient Refactor

`GitClient.__init__` changes from taking a `Config` to taking explicit values:

```python
class GitClient:
    def __init__(self, clone_url: str, clone_path: str, default_branch: str):
        self.clone_url = clone_url
        self.clone_path = clone_path
        self.default_branch = default_branch
```

All internal references to `self.config.clone_path` etc. become `self.clone_path`. Auth setup (`set_git_auth`) stays global.

### GitHubClient Refactor

```python
class GitHubClient:
    def __init__(self, repo: str):
        self.repo = repo
```

Auth setup (`set_gh_auth`) stays global.

### Bot Changes

**BaseBot** signature:

```python
class BaseBot:
    def __init__(self, config: Config, jira: JiraClient,
                 spec_ctx: RepoContext, impl_ctx: RepoContext):
        self.config = config
        self.jira = jira
        self.spec_ctx = spec_ctx
        self.impl_ctx = impl_ctx
```

`spec_dir()` uses `spec_ctx.clone_path` and `spec_ctx.specs_dir`. The old `self.git` and `self.github` accessors are removed — bots use `self.spec_ctx.git`, `self.impl_ctx.github`, etc.

**SpecifierBot / PlannerBot**: All operations use `self.spec_ctx` exclusively. Changes are mechanical — `self.git.` → `self.spec_ctx.git.`, `self.github.` → `self.spec_ctx.github.`.

**ImplementerBot**: Dual-context usage:

| Operation | Context |
|---|---|
| Check if plan PR is merged | `spec_ctx.github` |
| Clone workspace to read spec/plan | `spec_ctx.git` |
| Clone target to write code | `impl_ctx.git` |
| Run Claude | `impl_ctx.clone_path` (working dir) |
| Create impl branch, commit, push | `impl_ctx.git` |
| Create impl PR | `impl_ctx.github` |
| CI monitoring and fix | `impl_ctx` |
| Review comment handling on impl PR | `impl_ctx` |
| Recovery — check plan PR | `spec_ctx.github` |
| Recovery — check impl PR | `impl_ctx.github` |

The implementer must call `spec_ctx.git.ensure_repo_cloned()` before reading plan files, in addition to `impl_ctx.git.ensure_repo_cloned()`.

### Claude Runner Changes

`run_claude_on_repo` takes an explicit `clone_path` parameter instead of using `config.clone_path`:

```python
def run_claude_on_repo(self, bot_name, issue_key, prompt,
                       tools, max_turns, max_budget, clone_path):
```

`run_claude` in `claude_runner.py` takes `clone_path` as an explicit argument.

- SpecifierBot/PlannerBot pass `self.spec_ctx.clone_path`
- ImplementerBot passes `self.impl_ctx.clone_path`

### Template and Prompt Adjustments

The implement prompt template uses a `{{SPEC_PATH}}` placeholder. When workspace is separate, this receives the absolute path to spec/plan files in the workspace clone. When same-repo, it receives a relative path (preserving current behavior).

```python
# ImplementerBot._implement_issue
if self.spec_ctx is not self.impl_ctx:
    spec_path = os.path.join(self.spec_ctx.clone_path,
                             self.spec_ctx.specs_dir, issue_key)
else:
    spec_path = os.path.join(self.spec_ctx.specs_dir, issue_key)
```

Impl PR body uses cross-repo references when workspace is configured:

```python
# workspace configured:
f"**Spec PR:** {self.spec_ctx.repo}#{spec_pr}"
# same repo:
f"**Spec PR:** #{spec_pr}"
```

### Startup Wiring (main.py)

Bots are constructed once per-watcher at startup and cached as a list of tuples. The polling loop iterates the pre-built list:

```python
# At startup — build bot instances per watcher
watcher_bots = []
for watcher in config.watchers:
    target_git = GitClient(config.clone_url, config.clone_path, config.default_branch)
    target_github = GitHubClient(config.repo)
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

        ws_git = GitClient(watcher.workspace_clone_url, ws_clone_path, ws_default_branch)
        ws_github = GitHubClient(watcher.workspace_repo)
        spec_ctx = RepoContext(
            repo=watcher.workspace_repo, clone_url=watcher.workspace_clone_url,
            clone_path=ws_clone_path, default_branch=ws_default_branch,
            specs_dir=ws_specs_dir, git=ws_git, github=ws_github,
        )
    else:
        spec_ctx = target_ctx

    watcher_bots.append((
        watcher,
        SpecifierBot(config, jira, spec_ctx, target_ctx),
        PlannerBot(config, jira, spec_ctx, target_ctx),
        ImplementerBot(config, jira, spec_ctx, target_ctx),
    ))

# Polling loop iterates pre-built list
while not shutdown.is_set():
    for watcher, specifier, planner, implementer in watcher_bots:
        specifier.run_pass(watcher)
        planner.run_pass(watcher)
        implementer.run_pass(watcher)
```

JIRA client stays shared. Auth setup stays global and runs once before the loop.

### Edge Cases

1. **GitHub App installation**: Must be installed on both the workspace repo and the target repo. Same token works for both. Deployment requirement, not a code change.

2. **Shared workspace clone**: Multiple watchers with different target repos but the same workspace repo share the same clone on disk. Safe because the single-threaded polling loop runs one watcher at a time, and `ensure_repo_cloned` fetches/resets before use.

3. **Stale spec/plan reads**: ImplementerBot must call `spec_ctx.git.ensure_repo_cloned()` before reading plan files to get the latest merged content.

4. **Recovery passes**: Implementer recovery checks both plan PR (via `spec_ctx.github`) and impl PR (via `impl_ctx.github`). Specifier/planner recovery uses `spec_ctx` only.

### What Stays Unchanged

- JIRA client and label state machine
- Budget tracking
- Review comment handling logic (`review.py`) — just receives the appropriate github client
- GitHub App auth setup
- CI fix loop (operates entirely on impl_ctx)
- Metrics, logging, signal handling
- Spec/plan prompt templates (only impl template changes)
