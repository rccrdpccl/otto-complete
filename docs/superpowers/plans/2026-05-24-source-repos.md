# Source Repos per Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each watcher to declare read-only source repos (with independent platform/auth/branch) so all three bots can give Claude reference access to external codebases.

**Architecture:** New `SourceRepoConfig` (config-time) and `SourceRepo` (runtime) dataclasses. `main.py` builds a `GitClient` per source repo and passes a `list[SourceRepo]` to all bots via `BaseBot`. Bots clone source repos before Claude invocation and inject absolute paths into prompts via a `{{SOURCE_REPOS}}` template placeholder.

**Tech Stack:** Python dataclasses, PyYAML config parsing, existing `GitClient` / `AuthProvider` / `PatAuth` / `GitHubAppAuth` classes.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `otto_complete/config.py` | Modify | Add `SourceRepoConfig`, `SourceRepo` dataclasses; add `source_repos` field to `Watcher`; parse source repos in `load_config()` |
| `otto_complete/main.py` | Modify | Add `_build_source_auth()`; build `SourceRepo` list per watcher; pass to bot constructors |
| `otto_complete/bots/base.py` | Modify | Accept `source_repos` param; add `ensure_source_repos_cloned()` and `format_source_repos_section()` helpers |
| `otto_complete/bots/specifier.py` | Modify | Clone source repos and pass `SOURCE_REPOS` to templates |
| `otto_complete/bots/planner.py` | Modify | Clone source repos and pass `SOURCE_REPOS` to templates |
| `otto_complete/bots/implementer.py` | Modify | Clone source repos and pass `SOURCE_REPOS` to templates (all 3 prompt sites) |
| `templates/spec-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/plan-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/implement-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/ci-fix-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/impl-review-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/spec-review-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |
| `templates/plan-review-prompt.md` | Modify | Add `{{SOURCE_REPOS}}` placeholder |

---

### Task 1: Add SourceRepoConfig and SourceRepo dataclasses to config.py

**Files:**
- Modify: `otto_complete/config.py:1-13` (imports and pre-Watcher area)

- [ ] **Step 1: Add the SourceRepoConfig dataclass**

Add after the existing imports (line 8), before the `Watcher` class (line 14):

```python
@dataclass
class SourceRepoConfig:
    repo: str
    clone_url: str
    branch: str = ""
    platform: str = "github"
    auth_method: str = "pat"
    token_env: str = ""
    gitlab_url: str = ""
```

- [ ] **Step 2: Add the SourceRepo runtime dataclass**

Add after `SourceRepoConfig`, before `Watcher`:

```python
@dataclass
class SourceRepo:
    repo: str
    clone_path: str
    branch: str
    git: GitClient
```

The `GitClient` import is already available via `TYPE_CHECKING` on line 10.

- [ ] **Step 3: Commit**

```bash
git add otto_complete/config.py
git commit -m "add SourceRepoConfig and SourceRepo dataclasses"
```

---

### Task 2: Add source_repos field to Watcher and parse in load_config()

**Files:**
- Modify: `otto_complete/config.py:14-25` (Watcher class)
- Modify: `otto_complete/config.py:94-128` (load_config function)

- [ ] **Step 1: Add source_repos field to Watcher**

Add to the `Watcher` dataclass, after the existing fields:

```python
    source_repos: list[SourceRepoConfig] = field(default_factory=list)
```

This requires adding `field` to the existing `from dataclasses import dataclass, field` import on line 4 (already imported).

- [ ] **Step 2: Parse source_repos in load_config()**

In the `load_config()` function, inside the `for w in raw.pop("watchers", []):` loop, after the existing `gitlab_url` line (line 122), add source repo parsing:

```python
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
            ))
```

Then add `source_repos=source_repo_configs` to the `Watcher(...)` constructor call on line 113.

- [ ] **Step 3: Verify syntax**

```bash
python -c "from otto_complete.config import load_config, Watcher, SourceRepoConfig, SourceRepo; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add otto_complete/config.py
git commit -m "add source_repos to Watcher config and parse from YAML"
```

---

### Task 3: Add _build_source_auth() and build SourceRepo list in main.py

**Files:**
- Modify: `otto_complete/main.py:1-6` (imports)
- Modify: `otto_complete/main.py:24-46` (after _build_auth)
- Modify: `otto_complete/main.py:66-109` (watcher loop)

- [ ] **Step 1: Update imports**

Change line 6 from:

```python
from otto_complete.config import load_config, RepoContext
```

to:

```python
from otto_complete.config import load_config, RepoContext, SourceRepo
```

- [ ] **Step 2: Add _build_source_auth function**

Add after `_build_auth` (after line 46):

```python
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
```

- [ ] **Step 3: Build SourceRepo list in the watcher loop**

In the watcher loop, after the workspace context block (after the `else: spec_ctx = target_ctx` on line 102), add:

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
        if source_repos:
            log.info("Watcher %s%s: %d source repo(s): %s",
                     watcher.project,
                     f"/{watcher.component}" if watcher.component else "",
                     len(source_repos),
                     ", ".join(s.repo for s in source_repos))
```

- [ ] **Step 4: Pass source_repos to bot constructors**

Change the bot construction block from:

```python
        watcher_bots.append((
            watcher,
            SpecifierBot(config, jira, spec_ctx, target_ctx),
            PlannerBot(config, jira, spec_ctx, target_ctx),
            ImplementerBot(config, jira, spec_ctx, target_ctx),
        ))
```

to:

```python
        watcher_bots.append((
            watcher,
            SpecifierBot(config, jira, spec_ctx, target_ctx, source_repos),
            PlannerBot(config, jira, spec_ctx, target_ctx, source_repos),
            ImplementerBot(config, jira, spec_ctx, target_ctx, source_repos),
        ))
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "from otto_complete.main import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add otto_complete/main.py
git commit -m "build source repos per watcher and pass to bots"
```

---

### Task 4: Update BaseBot to accept source_repos and add helpers

**Files:**
- Modify: `otto_complete/bots/base.py:1-5` (imports)
- Modify: `otto_complete/bots/base.py:14-23` (BaseBot class)

- [ ] **Step 1: Update imports**

Change line 4 from:

```python
from otto_complete.config import Config, Watcher, RepoContext
```

to:

```python
from otto_complete.config import Config, Watcher, RepoContext, SourceRepo
```

- [ ] **Step 2: Update __init__ to accept source_repos**

Change the constructor (lines 17-22) from:

```python
    def __init__(self, config: Config, jira: JiraClient,
                 spec_ctx: RepoContext, impl_ctx: RepoContext):
        self.config = config
        self.jira = jira
        self.spec_ctx = spec_ctx
        self.impl_ctx = impl_ctx
```

to:

```python
    def __init__(self, config: Config, jira: JiraClient,
                 spec_ctx: RepoContext, impl_ctx: RepoContext,
                 source_repos: list[SourceRepo] | None = None):
        self.config = config
        self.jira = jira
        self.spec_ctx = spec_ctx
        self.impl_ctx = impl_ctx
        self.source_repos: list[SourceRepo] = source_repos or []
```

- [ ] **Step 3: Add ensure_source_repos_cloned() helper**

Add after the `run_claude_on_repo` method (after line 41):

```python
    def ensure_source_repos_cloned(self):
        for src in self.source_repos:
            src.git.ensure_repo_cloned()
```

- [ ] **Step 4: Add format_source_repos_section() helper**

Add after `ensure_source_repos_cloned`:

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

- [ ] **Step 5: Verify syntax**

```bash
python -c "from otto_complete.bots.base import BaseBot; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add otto_complete/bots/base.py
git commit -m "add source_repos support to BaseBot with clone and prompt helpers"
```

---

### Task 5: Add {{SOURCE_REPOS}} placeholder to all 7 prompt templates

**Files:**
- Modify: `templates/spec-prompt.md`
- Modify: `templates/plan-prompt.md`
- Modify: `templates/implement-prompt.md`
- Modify: `templates/ci-fix-prompt.md`
- Modify: `templates/impl-review-prompt.md`
- Modify: `templates/spec-review-prompt.md`
- Modify: `templates/plan-review-prompt.md`

- [ ] **Step 1: Add to spec-prompt.md**

Insert after line 8 (after `{{DESCRIPTION}}`), before `## Instructions`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 2: Add to plan-prompt.md**

Insert after line 4 (after `## Approved Specification: {{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md`), before `## Instructions`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 3: Add to implement-prompt.md**

Insert after line 6 (after `## Tasks: {{SPEC_PATH}}/tasks.md`), before `## Repository Conventions`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 4: Add to ci-fix-prompt.md**

Insert after line 9 (after `The spec is at...`), before `## Failed CI Checks`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 5: Add to impl-review-prompt.md**

Insert after line 7 (after `The spec is at...`), before `## Review Comments to Address`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 6: Add to spec-review-prompt.md**

Insert after line 7 (after `The spec is at...`), before `## Review Comments to Address`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 7: Add to plan-review-prompt.md**

Insert after line 7 (after `The plan is at...`), before `## Review Comments to Address`:

```markdown

{{SOURCE_REPOS}}

```

- [ ] **Step 8: Commit**

```bash
git add templates/
git commit -m "add SOURCE_REPOS placeholder to all prompt templates"
```

---

### Task 6: Wire source repos into SpecifierBot

**Files:**
- Modify: `otto_complete/bots/specifier.py:51-82` (_process method)
- Modify: `otto_complete/bots/specifier.py:124-149` (_address_comments method)

- [ ] **Step 1: Clone source repos in _process()**

In `_process()`, after `self.spec_ctx.git.ensure_repo_cloned()` (line 65), add:

```python
        self.ensure_source_repos_cloned()
```

- [ ] **Step 2: Pass SOURCE_REPOS to template in _process()**

Change the `render_template` call (lines 72-74) from:

```python
        prompt = self.render_template("spec-prompt.md",
            ISSUE_KEY=issue_key, SUMMARY=summary,
            DESCRIPTION=description, SPECS_DIR=self.spec_ctx.specs_dir)
```

to:

```python
        prompt = self.render_template("spec-prompt.md",
            ISSUE_KEY=issue_key, SUMMARY=summary,
            DESCRIPTION=description, SPECS_DIR=self.spec_ctx.specs_dir,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 3: Clone source repos in _address_comments()**

In `_address_comments()`, after `self.spec_ctx.git.ensure_repo_cloned()` (line 136), add:

```python
        self.ensure_source_repos_cloned()
```

- [ ] **Step 4: Pass SOURCE_REPOS to template in _address_comments()**

Change the `render_template` call (lines 140-141) from:

```python
        prompt = self.render_template("spec-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted)
```

to:

```python
        prompt = self.render_template("spec-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "from otto_complete.bots.specifier import SpecifierBot; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add otto_complete/bots/specifier.py
git commit -m "wire source repos into SpecifierBot prompts"
```

---

### Task 7: Wire source repos into PlannerBot

**Files:**
- Modify: `otto_complete/bots/planner.py:76-99` (_plan_issue method)
- Modify: `otto_complete/bots/planner.py:150-175` (_address_comments method)

- [ ] **Step 1: Clone source repos in _plan_issue()**

In `_plan_issue()`, after `self.spec_ctx.git.ensure_repo_cloned()` (line 79), add:

```python
        self.ensure_source_repos_cloned()
```

- [ ] **Step 2: Pass SOURCE_REPOS to template in _plan_issue()**

Change the `render_template` call (lines 90-91) from:

```python
        prompt = self.render_template("plan-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir)
```

to:

```python
        prompt = self.render_template("plan-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 3: Clone source repos in _address_comments()**

In `_address_comments()`, after `self.spec_ctx.git.ensure_repo_cloned()` (line 162), add:

```python
        self.ensure_source_repos_cloned()
```

- [ ] **Step 4: Pass SOURCE_REPOS to template in _address_comments()**

Change the `render_template` call (lines 166-167) from:

```python
        prompt = self.render_template("plan-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted)
```

to:

```python
        prompt = self.render_template("plan-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "from otto_complete.bots.planner import PlannerBot; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add otto_complete/bots/planner.py
git commit -m "wire source repos into PlannerBot prompts"
```

---

### Task 8: Wire source repos into ImplementerBot

**Files:**
- Modify: `otto_complete/bots/implementer.py:112-141` (_implement_issue method)
- Modify: `otto_complete/bots/implementer.py:230-265` (_perform_ci_fix method)
- Modify: `otto_complete/bots/implementer.py:325-360` (_address_comments method)

The ImplementerBot has three distinct Claude invocation sites that all need source repo context.

- [ ] **Step 1: Clone source repos and pass to template in _implement_issue()**

In `_implement_issue()`, after `self.impl_ctx.git.ensure_repo_cloned()` (line 116), add:

```python
        self.ensure_source_repos_cloned()
```

Change the `render_template` call (lines 133-134) from:

```python
        prompt = self.render_template("implement-prompt.md",
            ISSUE_KEY=issue_key, SPEC_PATH=spec_path)
```

to:

```python
        prompt = self.render_template("implement-prompt.md",
            ISSUE_KEY=issue_key, SPEC_PATH=spec_path,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 2: Clone source repos and pass to template in _perform_ci_fix()**

In `_perform_ci_fix()`, after `self.impl_ctx.git.ensure_repo_cloned()` (line 234), add:

```python
        self.ensure_source_repos_cloned()
```

Change the `render_template` call (lines 253-258) from:

```python
        prompt = self.render_template("ci-fix-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt,
            PR_NUMBER=str(pr_number), ATTEMPT_NUMBER=str(attempt_number),
            MAX_ATTEMPTS=str(cfg.ci_max_retries),
            FAILED_CHECKS=failed_checks_text,
            LOG_URLS=log_urls)
```

to:

```python
        prompt = self.render_template("ci-fix-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt,
            PR_NUMBER=str(pr_number), ATTEMPT_NUMBER=str(attempt_number),
            MAX_ATTEMPTS=str(cfg.ci_max_retries),
            FAILED_CHECKS=failed_checks_text,
            LOG_URLS=log_urls,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 3: Clone source repos and pass to template in _address_comments()**

In `_address_comments()`, after `self.impl_ctx.git.ensure_repo_cloned()` (line 338), add:

```python
        self.ensure_source_repos_cloned()
```

Change the `render_template` call (lines 352-353) from:

```python
        prompt = self.render_template("impl-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt, COMMENTS=formatted)
```

to:

```python
        prompt = self.render_template("impl-review-prompt.md",
            ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt, COMMENTS=formatted,
            SOURCE_REPOS=self.format_source_repos_section())
```

- [ ] **Step 4: Verify syntax**

```bash
python -c "from otto_complete.bots.implementer import ImplementerBot; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add otto_complete/bots/implementer.py
git commit -m "wire source repos into ImplementerBot prompts"
```

---

### Task 9: End-to-end verification

- [ ] **Step 1: Verify all modules import cleanly**

```bash
python -c "
from otto_complete.config import load_config, Watcher, SourceRepoConfig, SourceRepo, RepoContext
from otto_complete.bots.base import BaseBot
from otto_complete.bots.specifier import SpecifierBot
from otto_complete.bots.planner import PlannerBot
from otto_complete.bots.implementer import ImplementerBot
from otto_complete.main import main
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Verify backward compatibility — config without source_repos**

```bash
python -c "
import yaml, tempfile, os
config_yaml = '''
repo: test/repo
clone_url: https://github.com/test/repo.git
watchers:
  - project: TEST
'''
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
    f.write(config_yaml)
    path = f.name
os.environ['OTTO_CONFIG'] = path
os.environ.setdefault('JIRA_URL', 'https://jira.example.com')
os.environ.setdefault('JIRA_USER', 'test')
os.environ.setdefault('JIRA_API_TOKEN', 'test')
from otto_complete.config import load_config
cfg = load_config()
assert len(cfg.watchers) == 1
assert cfg.watchers[0].source_repos == []
print('Backward compat OK')
os.unlink(path)
"
```

Expected: `Backward compat OK`

- [ ] **Step 3: Verify source_repos parsing**

```bash
python -c "
import yaml, tempfile, os
config_yaml = '''
repo: test/repo
clone_url: https://github.com/test/repo.git
watchers:
  - project: TEST
    source_repos:
      - repo: org/source1
        clone_url: https://github.com/org/source1.git
        branch: develop
        platform: github
        auth:
          method: pat
          token_env: SRC1_TOKEN
      - repo: org/source2
        clone_url: https://gitlab.com/org/source2.git
        platform: gitlab
        gitlab_url: https://gitlab.com
        auth:
          method: pat
          token_env: SRC2_TOKEN
'''
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
    f.write(config_yaml)
    path = f.name
os.environ['OTTO_CONFIG'] = path
os.environ.setdefault('JIRA_URL', 'https://jira.example.com')
os.environ.setdefault('JIRA_USER', 'test')
os.environ.setdefault('JIRA_API_TOKEN', 'test')
from otto_complete.config import load_config
cfg = load_config()
w = cfg.watchers[0]
assert len(w.source_repos) == 2
s1 = w.source_repos[0]
assert s1.repo == 'org/source1'
assert s1.branch == 'develop'
assert s1.auth_method == 'pat'
assert s1.token_env == 'SRC1_TOKEN'
s2 = w.source_repos[1]
assert s2.platform == 'gitlab'
assert s2.gitlab_url == 'https://gitlab.com'
print('Source repos parsing OK')
os.unlink(path)
"
```

Expected: `Source repos parsing OK`

- [ ] **Step 4: Verify format_source_repos_section() output**

```bash
python -c "
from otto_complete.config import SourceRepo
from otto_complete.bots.base import BaseBot

class FakeBot(BaseBot):
    def run_pass(self, watcher): pass

# Test empty
bot = FakeBot.__new__(FakeBot)
bot.source_repos = []
assert bot.format_source_repos_section() == ''

# Test with repos
bot.source_repos = [
    SourceRepo(repo='org/svc', clone_path='/tmp/ai-agent/source-org--svc', branch='main', git=None),
    SourceRepo(repo='org/lib', clone_path='/tmp/ai-agent/source-org--lib', branch='v2', git=None),
]
section = bot.format_source_repos_section()
assert 'org/svc' in section
assert '/tmp/ai-agent/source-org--svc' in section
assert 'branch: main' in section
assert 'org/lib' in section
assert 'branch: v2' in section
assert 'Read-Only' in section
print('format_source_repos_section OK')
"
```

Expected: `format_source_repos_section OK`

- [ ] **Step 5: Verify template placeholders exist in all 7 templates**

```bash
grep -l "{{SOURCE_REPOS}}" templates/*.md | wc -l
```

Expected: `7`

- [ ] **Step 6: Commit (if any fixes were needed)**

Only commit if earlier steps required fixes. Otherwise, skip.
