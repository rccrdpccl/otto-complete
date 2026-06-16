# Workspace Repo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow spec/plan phases to use a separate workspace repo while implementation targets an external repo, configured per-watcher.

**Architecture:** Introduce a `RepoContext` dataclass that bundles a repo's identity (name, URLs, paths) with its `GitClient` and `GitHubClient`. Refactor `GitClient` and `GitHubClient` to take explicit values instead of the full `Config`. Each watcher resolves to either one context (backward compatible) or two (workspace + target). Bots receive the appropriate context(s).

**Tech Stack:** Python 3, dataclasses, PyYAML

**Spec:** `docs/superpowers/specs/2026-05-23-workspace-repo-design.md`

---

### Task 1: Add workspace fields to Watcher and RepoContext to config.py

**Files:**
- Modify: `otto_complete/config.py:1-82`

- [ ] **Step 1: Add workspace fields to the Watcher dataclass**

In `otto_complete/config.py`, add three fields to the existing `Watcher` dataclass:

```python
@dataclass
class Watcher:
    project: str
    component: str = ""
    workspace_repo: str = ""
    workspace_clone_url: str = ""
    workspace_default_branch: str = ""
```

- [ ] **Step 2: Add the RepoContext dataclass**

Add a new dataclass after `Config` in `otto_complete/config.py`. It uses forward-reference strings for `GitClient` and `GitHubClient` to avoid circular imports (these classes are defined in `clients/`):

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otto_complete.clients.git import GitClient
    from otto_complete.clients.github import GitHubClient


@dataclass
class RepoContext:
    repo: str
    clone_url: str
    clone_path: str
    default_branch: str
    specs_dir: str
    git: GitClient
    github: GitHubClient
```

Note: `from __future__ import annotations` goes at the very top of the file (line 1), before all other imports.

- [ ] **Step 3: Update load_config to parse new watcher fields**

In `load_config()`, the watcher parsing already uses `w.get(...)` for `component`. Add the three new fields:

```python
watchers = [
    Watcher(
        project=w["project"],
        component=w.get("component", ""),
        workspace_repo=w.get("workspace_repo", ""),
        workspace_clone_url=w.get("workspace_clone_url", ""),
        workspace_default_branch=w.get("workspace_default_branch", ""),
    )
    for w in raw.pop("watchers", [])
]
```

- [ ] **Step 4: Commit**

```bash
git add otto_complete/config.py
git commit -m "add RepoContext dataclass and workspace fields to Watcher"
```

---

### Task 2: Refactor GitClient to take explicit values

**Files:**
- Modify: `otto_complete/clients/git.py:35-112`

- [ ] **Step 1: Change GitClient.__init__ signature**

Replace the current `__init__` that takes `Config`:

```python
class GitClient:
    def __init__(self, config: Config):
        self.config = config
```

With explicit parameters:

```python
class GitClient:
    def __init__(self, clone_url: str, clone_path: str, default_branch: str):
        self.clone_url = clone_url
        self.clone_path = clone_path
        self.default_branch = default_branch
```

Remove the `from otto_complete.config import Config` import at the top of the file.

- [ ] **Step 2: Update ensure_repo_cloned**

Replace all `cfg = self.config` / `cfg.clone_path` / `cfg.clone_url` / `cfg.default_branch` / `cfg.work_dir` references with `self.clone_path` / `self.clone_url` / `self.default_branch`. Derive `work_dir` from `self.clone_path`:

```python
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
```

- [ ] **Step 3: Update _update_remotes**

```python
def _update_remotes(self):
    if _gh_auth is None:
        return
    origin_url = _authed_url(self.clone_url)
    _git(self.clone_path, "remote", "set-url", "origin", origin_url)
```

- [ ] **Step 4: Update create_branch**

```python
def create_branch(self, branch: str):
    _git(self.clone_path, "checkout", self.default_branch)
    _git(self.clone_path, "checkout", "-b", branch)
```

- [ ] **Step 5: Update checkout_branch**

```python
def checkout_branch(self, branch: str):
    self._update_remotes()
    _git(self.clone_path, "fetch", "origin")
    _git(self.clone_path, "checkout", branch)
    _git(self.clone_path, "pull", "origin", branch)
```

- [ ] **Step 6: Update remaining methods**

Replace `self.config.clone_path` with `self.clone_path` in `status`, `add`, `commit`, `push_branch`, and `remove_file`:

`status`:
```python
def status(self, pathspec: str = "") -> str:
    args = ["status", "--porcelain"]
    if pathspec:
        args += ["--", pathspec]
    result = _git(self.clone_path, *args)
    return result.stdout.strip()
```

`add`:
```python
def add(self, path: str = "."):
    if path == ".":
        _git(self.clone_path, "add", "-A")
    else:
        _git(self.clone_path, "add", path)
```

`commit`:
```python
def commit(self, message: str):
    _git(self.clone_path, "commit", "-m", message)
```

`push_branch`:
```python
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
```

`remove_file`:
```python
def remove_file(self, path: str):
    full_path = os.path.join(self.clone_path, path)
    if os.path.exists(full_path):
        os.remove(full_path)
```

- [ ] **Step 7: Commit**

```bash
git add otto_complete/clients/git.py
git commit -m "refactor GitClient to take explicit clone_url, clone_path, default_branch"
```

---

### Task 3: Refactor GitHubClient to take explicit repo

**Files:**
- Modify: `otto_complete/clients/github.py:32-34`

- [ ] **Step 1: Change GitHubClient.__init__ signature**

Replace:

```python
class GitHubClient:
    def __init__(self, config: Config):
        self.repo = config.repo
```

With:

```python
class GitHubClient:
    def __init__(self, repo: str):
        self.repo = repo
```

Remove the `from otto_complete.config import Config` import at the top of the file.

- [ ] **Step 2: Commit**

```bash
git add otto_complete/clients/github.py
git commit -m "refactor GitHubClient to take explicit repo string"
```

---

### Task 4: Refactor claude_runner.py to take explicit clone_path

**Files:**
- Modify: `otto_complete/claude_runner.py:19-48`

- [ ] **Step 1: Add clone_path parameter to run_claude**

Change the `run_claude` function signature to accept `clone_path` instead of reading from `config.clone_path`. Remove the `config` parameter entirely since it's only used for `config.clone_path`:

```python
def run_claude(
    bot: str,
    issue_key: str,
    prompt: str,
    tools: str,
    max_turns: int,
    max_budget: str,
    clone_path: str,
) -> tuple[int, dict]:
    if _budget and not _budget.can_spend(float(max_budget)):
        log.warning("Global budget exhausted ($%.2f / $%.2f) — skipping %s/%s",
                     _budget.spent, _budget.max_budget, bot, issue_key)
        return 1, {}

    cmd = [
        "claude", "-p", prompt,
        "--plugin-dir", "/opt/superpowers",
        "--allowedTools", tools,
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(max_budget),
        "--output-format", "json",
    ]

    log.info("Running Claude for %s/%s (max %d turns, $%s budget)", bot, issue_key, max_turns, max_budget)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=clone_path, timeout=1800,
        )
        exit_code = result.returncode
        output = {}
        if result.stdout.strip():
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                log.warning("Failed to parse Claude JSON output")
    except subprocess.TimeoutExpired:
        log.error("Claude timed out for %s/%s", bot, issue_key)
        exit_code = 1
        output = {}
    except Exception as e:
        log.error("Claude failed for %s/%s: %s", bot, issue_key, e)
        exit_code = 1
        output = {}

    record_run(bot, issue_key, output, exit_code)

    if _budget:
        _budget.record(output.get("total_cost_usd", 0.0))

    if exit_code != 0:
        log.warning("Claude exited with code %d for %s/%s (may still have produced changes)", exit_code, bot, issue_key)

    return exit_code, output
```

Remove the `from otto_complete.config import Config` import.

- [ ] **Step 2: Commit**

```bash
git add otto_complete/claude_runner.py
git commit -m "refactor run_claude to take explicit clone_path parameter"
```

---

### Task 5: Refactor BaseBot to use RepoContext

**Files:**
- Modify: `otto_complete/bots/base.py:1-59`

- [ ] **Step 1: Update imports and __init__ signature**

Replace the current imports and `__init__`:

```python
import logging
import os

from otto_complete.config import Config, Watcher, RepoContext
from otto_complete.clients.jira import JiraClient
from otto_complete.claude_runner import run_claude

log = logging.getLogger(__name__)

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.normpath(os.path.join(_PACKAGE_ROOT, "..", "templates"))


class BaseBot:
    name = "base"

    def __init__(self, config: Config, jira: JiraClient,
                 spec_ctx: RepoContext, impl_ctx: RepoContext):
        self.config = config
        self.jira = jira
        self.spec_ctx = spec_ctx
        self.impl_ctx = impl_ctx
```

Remove the imports of `GitHubClient`, `GitClient` — they're no longer direct dependencies.

- [ ] **Step 2: Update run_claude_on_repo to take clone_path**

```python
def run_claude_on_repo(
    self, bot_name: str, issue_key: str, prompt: str,
    tools: str, max_turns: int, max_budget: str,
    clone_path: str,
) -> int:
    exit_code, _ = run_claude(bot_name, issue_key, prompt, tools, max_turns, max_budget, clone_path)
    return exit_code
```

- [ ] **Step 3: Update spec_dir and replies_file to use spec_ctx**

```python
def spec_dir(self, issue_key: str) -> str:
    return os.path.join(self.spec_ctx.clone_path, self.spec_ctx.specs_dir, issue_key)

def replies_file(self, issue_key: str) -> str:
    return os.path.join(self.spec_dir(issue_key), "review-replies.json")
```

- [ ] **Step 4: Remove commit_and_push from BaseBot**

The `commit_and_push` helper references `self.git` which no longer exists. It's only used in a generic sense — bots can call the git methods on their context directly. Remove the `commit_and_push` method entirely. (It is not called by any bot currently — specifier, planner, and implementer each do their own git add/commit/push inline.)

Verify it's unused first:

```bash
grep -rn "commit_and_push" otto_complete/
```

If it IS used somewhere, keep it but have callers pass a `GitClient` explicitly. Based on the current code, it's not called.

- [ ] **Step 5: Commit**

```bash
git add otto_complete/bots/base.py
git commit -m "refactor BaseBot to use RepoContext instead of direct git/github clients"
```

---

### Task 6: Update SpecifierBot to use spec_ctx

**Files:**
- Modify: `otto_complete/bots/specifier.py:1-155`

- [ ] **Step 1: Update imports**

Remove any direct imports of `GitClient`, `GitHubClient` if present. The imports should be:

```python
import logging
import os

from otto_complete.bots.base import BaseBot
from otto_complete.config import Watcher
from otto_complete.review import (
    collect_unaddressed_comments,
    format_comments_for_prompt,
    post_review_replies,
)

log = logging.getLogger(__name__)
```

- [ ] **Step 2: Update _recover to use spec_ctx**

Replace `self.github.` with `self.spec_ctx.github.` and `self.config.branch_prefix_spec` stays as-is (it's on Config):

```python
def _recover(self, issue_key: str):
    branch = f"{self.config.branch_prefix_spec}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(branch)

    if pr_number:
        log.info("%s: recovering — spec PR #%d exists, fixing label", issue_key, pr_number)
        self.jira.swap_label(issue_key, "ai:specifying", "ai:spec-review")
    else:
        log.info("%s: recovering — no spec PR found, retrying from scratch", issue_key)
        self.jira.remove_label(issue_key, "ai:specifying")
        self._process(issue_key)
```

- [ ] **Step 3: Update _process to use spec_ctx**

Replace `self.git.` with `self.spec_ctx.git.`, `self.github.` with `self.spec_ctx.github.`. Use `self.spec_ctx.specs_dir` instead of `cfg.specs_dir`. Use `self.spec_ctx.default_branch` for the PR base. Pass `self.spec_ctx.clone_path` to `run_claude_on_repo`:

```python
def _process(self, issue_key: str):
    cfg = self.config

    log.info("Specifying %s", issue_key)
    if not self.jira.add_label(issue_key, "ai:specifying"):
        return

    summary, description = self.jira.get_details(issue_key)
    if not summary:
        log.error("Failed to fetch JIRA details for %s", issue_key)
        self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Failed to fetch JIRA details")
        return

    self.spec_ctx.git.ensure_repo_cloned()
    branch = f"{cfg.branch_prefix_spec}{issue_key}"
    self.spec_ctx.git.create_branch(branch)

    spec_dir = self.spec_dir(issue_key)
    os.makedirs(spec_dir, exist_ok=True)

    prompt = self.render_template("spec-prompt.md",
        ISSUE_KEY=issue_key, SUMMARY=summary,
        DESCRIPTION=description, SPECS_DIR=self.spec_ctx.specs_dir)

    log.info("Running Claude for %s (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_spec, cfg.max_budget_spec)

    tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(git log*),Bash(git diff*),Bash(ls *),Bash(cat *)"
    self.run_claude_on_repo("specifier", issue_key, prompt, tools,
                            cfg.max_turns_spec, cfg.max_budget_spec,
                            self.spec_ctx.clone_path)

    spec_file = os.path.join(spec_dir, "spec.md")
    if not os.path.isfile(spec_file):
        log.error("Claude did not produce spec file: %s", spec_file)
        self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Spec file not created")
        return

    log.info("Spec file created, committing")
    self.spec_ctx.git.add(os.path.join(self.spec_ctx.specs_dir, issue_key))
    self.spec_ctx.git.commit(f"{issue_key}(spec): create specification")
    self.spec_ctx.git.push_branch(branch)

    pr_body = (
        f"## Specification for {issue_key}\n\n"
        f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
        f"**Summary:** {summary}\n\n"
        f"This PR contains a formal specification — **what** to build and **why**.\n"
        f"Review the spec at `{self.spec_ctx.specs_dir}/{issue_key}/spec.md`.\n\n"
        f"### Review checklist\n"
        f"- [ ] Requirements are clear and testable\n"
        f"- [ ] Acceptance criteria are complete\n"
        f"- [ ] Out of scope is correctly defined\n"
        f"- [ ] Open questions are answered (edit the spec if needed)\n\n"
        f"Once merged, the planner bot will generate an implementation plan as a follow-up PR."
    )

    pr_url = self.spec_ctx.github.create_pr(branch, f"spec: {issue_key} {summary}",
                                            pr_body, self.spec_ctx.default_branch, "ai:spec")

    if not pr_url or "error" in pr_url.lower():
        log.error("Failed to create PR for %s: %s", issue_key, pr_url)
        self.jira.swap_label(issue_key, "ai:specifying", "ai:error")
        self.jira.add_comment(issue_key, f"otto-complete error: Spec PR creation failed: {pr_url}")
        return

    self.jira.swap_label(issue_key, "ai:specifying", "ai:spec-review")
    self.jira.add_comment(issue_key, f"Specification PR opened: {pr_url}")
    self.jira.transition(issue_key, "In Progress")
    log.info("Spec PR created for %s: %s", issue_key, pr_url)
```

- [ ] **Step 4: Update _address_comments to use spec_ctx**

```python
def _address_comments(self, issue_key: str):
    cfg = self.config
    branch = f"{cfg.branch_prefix_spec}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(branch)
    if not pr_number:
        return

    comments = collect_unaddressed_comments(self.spec_ctx.github, pr_number)
    if not comments:
        return

    log.info("%s: found unaddressed review comments on PR #%d", issue_key, pr_number)
    self.spec_ctx.git.ensure_repo_cloned()
    self.spec_ctx.git.checkout_branch(branch)

    formatted = format_comments_for_prompt(comments)
    prompt = self.render_template("spec-review-prompt.md",
        ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted)

    log.info("Running Claude for %s review (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_review, cfg.max_budget_review)

    tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(cat *),Bash(ls *)"
    self.run_claude_on_repo("specifier-review", issue_key, prompt, tools,
                            cfg.max_turns_review, cfg.max_budget_review,
                            self.spec_ctx.clone_path)

    spec_path = os.path.join(self.spec_ctx.specs_dir, issue_key, "spec.md")
    changes = self.spec_ctx.git.status(spec_path)
    if changes:
        log.info("%s: spec updated, committing", issue_key)
        self.spec_ctx.git.add(spec_path)
        self.spec_ctx.git.commit(f"{issue_key}(spec): address review comments")
        self.spec_ctx.git.push_branch(branch, force=True)

    post_review_replies(self.spec_ctx.github, issue_key, pr_number, comments, self.replies_file(issue_key))
```

- [ ] **Step 5: Commit**

```bash
git add otto_complete/bots/specifier.py
git commit -m "update SpecifierBot to use spec_ctx"
```

---

### Task 7: Update PlannerBot to use spec_ctx

**Files:**
- Modify: `otto_complete/bots/planner.py:1-181`

- [ ] **Step 1: Update _recover to use spec_ctx**

```python
def _recover(self, issue_key: str):
    branch = f"{self.config.branch_prefix_plan}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(branch)

    if pr_number:
        log.info("%s: recovering — plan PR #%d exists, fixing label", issue_key, pr_number)
        self.jira.swap_label(issue_key, "ai:planning", "ai:plan-review")
        return

    spec_branch = f"{self.config.branch_prefix_spec}{issue_key}"
    spec_pr = self.spec_ctx.github.find_pr_by_branch(spec_branch)
    if not spec_pr or not self.spec_ctx.github.pr_is_merged(spec_pr):
        log.warning("%s: recovering — no plan PR and spec not merged, cannot retry", issue_key)
        return

    log.info("%s: recovering — no plan PR found, retrying planning", issue_key)
    self._plan_issue(issue_key)
```

- [ ] **Step 2: Update _check_and_plan to use spec_ctx**

```python
def _check_and_plan(self, issue_key: str):
    cfg = self.config
    spec_branch = f"{cfg.branch_prefix_spec}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(spec_branch)

    if not pr_number:
        log.warning("%s: no spec PR found for branch %s", issue_key, spec_branch)
        return

    if not self.spec_ctx.github.pr_is_merged(pr_number):
        log.info("%s: spec PR #%d not yet merged", issue_key, pr_number)
        return

    log.info("%s: spec PR #%d merged, starting planning", issue_key, pr_number)
    if not self.jira.swap_label(issue_key, "ai:spec-review", "ai:planning"):
        return

    self._plan_issue(issue_key)
```

- [ ] **Step 3: Update _plan_issue to use spec_ctx**

```python
def _plan_issue(self, issue_key: str):
    cfg = self.config

    self.spec_ctx.git.ensure_repo_cloned()
    branch = f"{cfg.branch_prefix_plan}{issue_key}"
    self.spec_ctx.git.create_branch(branch)

    spec_file = os.path.join(self.spec_dir(issue_key), "spec.md")
    if not os.path.isfile(spec_file):
        log.error("Spec file not found after merge: %s", spec_file)
        self.jira.swap_label(issue_key, "ai:planning", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Spec file missing from merged branch")
        return

    prompt = self.render_template("plan-prompt.md",
        ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir)

    log.info("Running Claude for %s (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_plan, cfg.max_budget_plan)

    tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(git log*),Bash(git diff*),Bash(ls *),Bash(cat *)"
    self.run_claude_on_repo("planner", issue_key, prompt, tools,
                            cfg.max_turns_plan, cfg.max_budget_plan,
                            self.spec_ctx.clone_path)

    plan_file = os.path.join(self.spec_dir(issue_key), "plan.md")
    if not os.path.isfile(plan_file):
        log.error("Claude did not produce plan file: %s", plan_file)
        self.jira.swap_label(issue_key, "ai:planning", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Plan file not created")
        return

    tasks_file = os.path.join(self.spec_dir(issue_key), "tasks.md")
    if not os.path.isfile(tasks_file):
        log.warning("Tasks file not created: %s (continuing without it)", tasks_file)

    log.info("Plan files created, committing")
    self.spec_ctx.git.add(os.path.join(self.spec_ctx.specs_dir, issue_key))
    self.spec_ctx.git.commit(f"{issue_key}(plan): create implementation plan and tasks")
    self.spec_ctx.git.push_branch(branch)

    summary, _ = self.jira.get_details(issue_key)
    spec_pr_number = self.spec_ctx.github.find_pr_by_branch(f"{cfg.branch_prefix_spec}{issue_key}")

    pr_body = (
        f"## Implementation Plan for {issue_key}\n\n"
        f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
        f"**Summary:** {summary}\n"
        f"**Spec PR:** #{spec_pr_number}\n\n"
        f"This PR contains the implementation plan and task breakdown.\n"
        f"Review the files at:\n"
        f"- `{self.spec_ctx.specs_dir}/{issue_key}/plan.md` — technical approach and design decisions\n"
        f"- `{self.spec_ctx.specs_dir}/{issue_key}/tasks.md` — ordered task breakdown\n\n"
        f"### Review checklist\n"
        f"- [ ] Plan approach is sound and follows existing patterns\n"
        f"- [ ] Task ordering is correct (dependencies respected)\n"
        f"- [ ] Testing strategy covers acceptance criteria from the spec\n"
        f"- [ ] Risks are identified and mitigated\n\n"
        f"Once merged, the implementer bot will execute these tasks and open a follow-up PR."
    )

    pr_url = self.spec_ctx.github.create_pr(branch, f"plan: {issue_key} {summary}",
                                            pr_body, self.spec_ctx.default_branch, "ai:plan")

    if not pr_url or "error" in pr_url.lower():
        log.error("Failed to create PR for %s: %s", issue_key, pr_url)
        self.jira.swap_label(issue_key, "ai:planning", "ai:error")
        self.jira.add_comment(issue_key, f"otto-complete error: Plan PR creation failed: {pr_url}")
        return

    self.jira.swap_label(issue_key, "ai:planning", "ai:plan-review")
    self.jira.add_comment(issue_key, f"Implementation plan PR opened: {pr_url}")
    log.info("Plan PR created for %s: %s", issue_key, pr_url)
```

Note: The plan PR body references the spec PR with `#{spec_pr_number}` — this is fine because both spec and plan PRs are in the same workspace repo.

- [ ] **Step 4: Update _address_comments to use spec_ctx**

```python
def _address_comments(self, issue_key: str):
    cfg = self.config
    branch = f"{cfg.branch_prefix_plan}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(branch)
    if not pr_number:
        return

    comments = collect_unaddressed_comments(self.spec_ctx.github, pr_number)
    if not comments:
        return

    log.info("%s: found unaddressed review comments on plan PR #%d", issue_key, pr_number)
    self.spec_ctx.git.ensure_repo_cloned()
    self.spec_ctx.git.checkout_branch(branch)

    formatted = format_comments_for_prompt(comments)
    prompt = self.render_template("plan-review-prompt.md",
        ISSUE_KEY=issue_key, SPECS_DIR=self.spec_ctx.specs_dir, COMMENTS=formatted)

    log.info("Running Claude for %s plan review (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_review, cfg.max_budget_review)

    tools = "Read,Write,Edit,Bash(find *),Bash(grep *),Bash(rg *),Bash(cat *),Bash(ls *)"
    self.run_claude_on_repo("planner-review", issue_key, prompt, tools,
                            cfg.max_turns_review, cfg.max_budget_review,
                            self.spec_ctx.clone_path)

    spec_path = os.path.join(self.spec_ctx.specs_dir, issue_key)
    changes = self.spec_ctx.git.status(spec_path)
    if changes:
        log.info("%s: plan updated, committing", issue_key)
        self.spec_ctx.git.add(spec_path)
        self.spec_ctx.git.commit(f"{issue_key}(plan): address review comments")
        self.spec_ctx.git.push_branch(branch, force=True)

    post_review_replies(self.spec_ctx.github, issue_key, pr_number, comments, self.replies_file(issue_key))
```

- [ ] **Step 5: Commit**

```bash
git add otto_complete/bots/planner.py
git commit -m "update PlannerBot to use spec_ctx"
```

---

### Task 8: Update ImplementerBot to use dual contexts

**Files:**
- Modify: `otto_complete/bots/implementer.py:1-342`

This is the largest change. The implementer uses `impl_ctx` for code operations and `spec_ctx` for reading spec/plan files and checking plan PR status.

- [ ] **Step 1: Update _recover_error to use impl_ctx**

```python
def _recover_error(self, issue_key: str):
    branch = f"{self.config.branch_prefix_impl}{issue_key}"
    pr_number = self.impl_ctx.github.find_pr_by_branch(branch)
    if pr_number and not self.impl_ctx.github.pr_is_merged(pr_number):
        log.info("%s: recovering from ai:error — open PR #%d found, moving to impl-review", issue_key, pr_number)
        self._reset_ci_attempts(issue_key)
        self.jira.swap_label(issue_key, "ai:error", "ai:impl-review")
```

- [ ] **Step 2: Update _recover to use dual contexts**

```python
def _recover(self, issue_key: str):
    branch = f"{self.config.branch_prefix_impl}{issue_key}"
    pr_number = self.impl_ctx.github.find_pr_by_branch(branch)

    if pr_number:
        log.info("%s: recovering — impl PR #%d exists, fixing label", issue_key, pr_number)
        self.jira.swap_label(issue_key, "ai:implementing", "ai:impl-review")
        return

    plan_branch = f"{self.config.branch_prefix_plan}{issue_key}"
    plan_pr = self.spec_ctx.github.find_pr_by_branch(plan_branch)
    if not plan_pr or not self.spec_ctx.github.pr_is_merged(plan_pr):
        log.warning("%s: recovering — no impl PR and plan not merged, cannot retry", issue_key)
        return

    log.info("%s: recovering — no impl PR found, retrying implementation", issue_key)
    self._implement_issue(issue_key)
```

- [ ] **Step 3: Update _recover_ci_fixer to use impl_ctx**

```python
def _recover_ci_fixer(self, issue_key: str):
    branch = f"{self.config.branch_prefix_impl}{issue_key}"
    pr_number = self.impl_ctx.github.find_pr_by_branch(branch)

    if not pr_number:
        log.warning("%s: recovering ci-fixing — no impl PR found, moving to error", issue_key)
        self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: CI fixing recovery failed — no impl PR found")
        return

    log.info("%s: recovering ci-fixing — impl PR #%d exists, returning to impl-review", issue_key, pr_number)
    self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:impl-review")
```

- [ ] **Step 4: Update _check_and_implement to use dual contexts**

```python
def _check_and_implement(self, issue_key: str):
    cfg = self.config
    plan_branch = f"{cfg.branch_prefix_plan}{issue_key}"
    pr_number = self.spec_ctx.github.find_pr_by_branch(plan_branch)

    if not pr_number:
        log.warning("%s: no plan PR found for branch %s", issue_key, plan_branch)
        return

    if not self.spec_ctx.github.pr_is_merged(pr_number):
        log.info("%s: plan PR #%d not yet merged", issue_key, pr_number)
        return

    log.info("%s: plan PR #%d merged, starting implementation", issue_key, pr_number)
    if not self.jira.swap_label(issue_key, "ai:plan-review", "ai:implementing"):
        return

    self._implement_issue(issue_key)
```

- [ ] **Step 5: Update _implement_issue with dual contexts and cross-repo PR refs**

This is the core dual-context method. It clones both repos, reads plan from workspace, runs Claude on target, and creates impl PR with cross-repo references:

```python
def _implement_issue(self, issue_key: str):
    cfg = self.config

    self.spec_ctx.git.ensure_repo_cloned()
    self.impl_ctx.git.ensure_repo_cloned()
    branch = f"{cfg.branch_prefix_impl}{issue_key}"
    self.impl_ctx.git.create_branch(branch)

    plan_file = os.path.join(self.spec_dir(issue_key), "plan.md")
    if not os.path.isfile(plan_file):
        log.error("Plan file not found after merge: %s", plan_file)
        self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Plan file missing from merged branch")
        return

    if self.spec_ctx is not self.impl_ctx:
        spec_path = os.path.join(self.spec_ctx.clone_path,
                                 self.spec_ctx.specs_dir, issue_key)
    else:
        spec_path = os.path.join(self.spec_ctx.specs_dir, issue_key)

    prompt = self.render_template("implement-prompt.md",
        ISSUE_KEY=issue_key, SPEC_PATH=spec_path)

    log.info("Running Claude for %s (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_impl, cfg.max_budget_impl)

    self.run_claude_on_repo("implementer", issue_key, prompt,
        "Read,Write,Edit,Bash", cfg.max_turns_impl, cfg.max_budget_impl,
        self.impl_ctx.clone_path)

    changes = self.impl_ctx.git.status()
    if not changes:
        log.error("No changes produced for %s", issue_key)
        self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
        self.jira.add_comment(issue_key, "otto-complete error: Implementation produced no changes")
        return

    log.info("Implementation produced changes, committing")
    self.impl_ctx.git.add()
    self.impl_ctx.git.commit(f"{issue_key}: implement plan")
    self.impl_ctx.git.push_branch(branch)

    summary, _ = self.jira.get_details(issue_key)
    spec_pr = self.spec_ctx.github.find_pr_by_branch(f"{cfg.branch_prefix_spec}{issue_key}")
    plan_pr = self.spec_ctx.github.find_pr_by_branch(f"{cfg.branch_prefix_plan}{issue_key}")

    if self.spec_ctx is not self.impl_ctx:
        spec_pr_ref = f"{self.spec_ctx.repo}#{spec_pr}"
        plan_pr_ref = f"{self.spec_ctx.repo}#{plan_pr}"
    else:
        spec_pr_ref = f"#{spec_pr}"
        plan_pr_ref = f"#{plan_pr}"

    pr_body = (
        f"## {issue_key}: {summary}\n\n"
        f"**JIRA:** {cfg.jira_url}/browse/{issue_key}\n"
        f"**Spec PR:** {spec_pr_ref}\n"
        f"**Plan PR:** {plan_pr_ref}\n\n"
        f"Implementation of the approved plan."
    )

    pr_url = self.impl_ctx.github.create_pr(branch, f"{issue_key}: {summary}",
                                            pr_body, self.impl_ctx.default_branch, "ai:impl")

    if not pr_url or "error" in pr_url.lower():
        log.error("Failed to create impl PR for %s: %s", issue_key, pr_url)
        self.jira.swap_label(issue_key, "ai:implementing", "ai:error")
        self.jira.add_comment(issue_key, f"otto-complete error: Impl PR creation failed: {pr_url}")
        return

    self._reset_ci_attempts(issue_key)
    self.jira.swap_label(issue_key, "ai:implementing", "ai:impl-review")
    self.jira.add_comment(issue_key, f"Implementation PR opened: {pr_url}")
    log.info("Implementation PR created for %s: %s", issue_key, pr_url)
```

Note: The PR body no longer references `specs_dir` file paths since the spec/plan files aren't in the target repo when workspace is separate.

- [ ] **Step 6: Update _check_and_fix_ci to use impl_ctx**

```python
def _check_and_fix_ci(self, issue_key: str):
    cfg = self.config
    impl_branch = f"{cfg.branch_prefix_impl}{issue_key}"
    pr_number = self.impl_ctx.github.find_pr_by_branch(impl_branch)
    if not pr_number:
        return

    if self.impl_ctx.github.pr_is_merged(pr_number):
        return

    if self.impl_ctx.github.checks_are_pending(pr_number):
        log.info("%s: CI checks still pending on PR #%d, skipping", issue_key, pr_number)
        return

    if self.impl_ctx.github.all_checks_pass(pr_number):
        return

    failed_checks = self.impl_ctx.github.get_failed_checks(pr_number)
    if not failed_checks:
        return

    attempt_count = self._get_ci_attempts(issue_key)

    if attempt_count >= cfg.ci_max_retries:
        log.warning("%s: CI fix attempts exhausted (%d >= %d)", issue_key, attempt_count, cfg.ci_max_retries)
        self.jira.swap_label(issue_key, "ai:impl-review", "ai:error")
        self.jira.add_comment(issue_key,
            f"otto-complete error: CI checks failed after {attempt_count} fix attempts. Manual intervention required.")
        return

    next_attempt = attempt_count + 1
    self._set_ci_attempts(issue_key, next_attempt)
    log.info("%s: CI failures detected on PR #%d, fix attempt %d/%d",
             issue_key, pr_number, next_attempt, cfg.ci_max_retries)

    if not self.jira.swap_label(issue_key, "ai:impl-review", "ai:ci-fixing"):
        return

    self._perform_ci_fix(issue_key, pr_number, impl_branch, failed_checks, next_attempt)

    self.jira.swap_label(issue_key, "ai:ci-fixing", "ai:impl-review")
```

- [ ] **Step 7: Update _perform_ci_fix to use impl_ctx**

Key subtlety: `self.spec_dir()` resolves to the workspace clone when workspace is separate. The `ci-analysis.json` and `review-replies.json` are transient working files — they must be cleaned up with direct `os.remove` (not through `git.remove_file`, which does relative-path arithmetic that breaks across clones). The ci-fix prompt passes `SPECS_DIR` as an absolute path to the workspace clone, so Claude can write ci-analysis.json there even though its cwd is the impl clone.

```python
def _perform_ci_fix(self, issue_key: str, pr_number: int, impl_branch: str,
                    failed_checks: list[dict], attempt_number: int):
    cfg = self.config

    self.impl_ctx.git.ensure_repo_cloned()
    self.impl_ctx.git.checkout_branch(impl_branch)

    analysis_file = os.path.join(self.spec_dir(issue_key), "ci-analysis.json")
    replies_file_path = self.replies_file(issue_key)
    if os.path.exists(analysis_file):
        os.remove(analysis_file)
    if os.path.exists(replies_file_path):
        os.remove(replies_file_path)

    failed_checks_text = self.impl_ctx.github.format_failed_checks(failed_checks)
    log_urls = "\n".join(c.get("link", "") for c in failed_checks[:10] if c.get("link"))

    if self.spec_ctx is not self.impl_ctx:
        specs_dir_for_prompt = os.path.join(self.spec_ctx.clone_path,
                                            self.spec_ctx.specs_dir)
    else:
        specs_dir_for_prompt = self.spec_ctx.specs_dir

    prompt = self.render_template("ci-fix-prompt.md",
        ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt,
        PR_NUMBER=str(pr_number), ATTEMPT_NUMBER=str(attempt_number),
        MAX_ATTEMPTS=str(cfg.ci_max_retries),
        FAILED_CHECKS=failed_checks_text,
        LOG_URLS=log_urls)

    log.info("Running Claude for %s CI fix (attempt %d, max %d turns, $%s budget)",
             issue_key, attempt_number, cfg.max_turns_ci_fix, cfg.max_budget_ci_fix)

    self.run_claude_on_repo("implementer-ci-fix", issue_key, prompt,
        "Read,Write,Edit,Bash", cfg.max_turns_ci_fix, cfg.max_budget_ci_fix,
        self.impl_ctx.clone_path)

    is_flake = False
    fix_summary = "Claude analysis completed"

    if os.path.isfile(analysis_file):
        try:
            with open(analysis_file) as f:
                analysis = json.load(f)
            is_flake = analysis.get("flake", False)
            fix_summary = analysis.get("summary", "No summary provided")
        except Exception:
            log.warning("%s: failed to parse ci-analysis.json", issue_key)
        os.remove(analysis_file)
    else:
        log.warning("%s: no ci-analysis.json produced", issue_key)

    if is_flake:
        log.info("%s: CI failure identified as flake, posting /retest", issue_key)
        self.impl_ctx.github.comment_on_pr(pr_number, "/retest")
        self.jira.add_comment(issue_key, f"CI fix attempt {attempt_number}: Flake detected — {fix_summary}")
        return

    changes = self.impl_ctx.git.status()
    if changes:
        log.info("%s: CI fix produced changes, committing", issue_key)
        self.impl_ctx.git.add()
        self.impl_ctx.git.commit(f"{issue_key}: CI fix attempt {attempt_number}")
        if self.impl_ctx.git.push_branch(impl_branch, force=True):
            self.jira.add_comment(issue_key, f"CI fix attempt {attempt_number}: {fix_summary}")
        else:
            log.warning("%s: push failed for CI fix", issue_key)
    else:
        log.warning("%s: CI fix attempt %d produced no changes", issue_key, attempt_number)
        self.jira.add_comment(issue_key,
            f"CI fix attempt {attempt_number}: No code changes produced — {fix_summary}")
```

- [ ] **Step 8: Update _address_comments to use impl_ctx**

Same pattern as CI fix: use direct `os.remove` for the transient replies file, and compute `specs_dir_for_prompt` for the review prompt.

```python
def _address_comments(self, issue_key: str):
    cfg = self.config
    impl_branch = f"{cfg.branch_prefix_impl}{issue_key}"
    pr_number = self.impl_ctx.github.find_pr_by_branch(impl_branch)
    if not pr_number:
        return

    comments = collect_unaddressed_comments(self.impl_ctx.github, pr_number)
    if not comments:
        return

    log.info("%s: found unaddressed review comments on impl PR #%d", issue_key, pr_number)
    self.impl_ctx.git.ensure_repo_cloned()
    self.impl_ctx.git.checkout_branch(impl_branch)

    replies_file_path = self.replies_file(issue_key)
    if os.path.exists(replies_file_path):
        os.remove(replies_file_path)

    formatted = format_comments_for_prompt(comments)

    if self.spec_ctx is not self.impl_ctx:
        specs_dir_for_prompt = os.path.join(self.spec_ctx.clone_path,
                                            self.spec_ctx.specs_dir)
    else:
        specs_dir_for_prompt = self.spec_ctx.specs_dir

    prompt = self.render_template("impl-review-prompt.md",
        ISSUE_KEY=issue_key, SPECS_DIR=specs_dir_for_prompt, COMMENTS=formatted)

    log.info("Running Claude for %s impl review (max %d turns, $%s budget)",
             issue_key, cfg.max_turns_review, cfg.max_budget_review)

    self.run_claude_on_repo("implementer-review", issue_key, prompt,
        "Read,Write,Edit,Bash", cfg.max_turns_review, cfg.max_budget_review,
        self.impl_ctx.clone_path)

    has_changes = bool(self.impl_ctx.git.status())
    if has_changes:
        log.info("%s: impl updated, committing", issue_key)
        if os.path.exists(replies_file_path):
            os.remove(replies_file_path)
        self.impl_ctx.git.add()
        self.impl_ctx.git.commit(f"{issue_key}: address review comments")
        self.impl_ctx.git.push_branch(impl_branch, force=True)
        self._reset_ci_attempts(issue_key)

    post_review_replies(self.impl_ctx.github, issue_key, pr_number, comments, replies_file_path, has_changes)
```

- [ ] **Step 9: Commit**

```bash
git add otto_complete/bots/implementer.py
git commit -m "update ImplementerBot to use dual spec_ctx/impl_ctx"
```

---

### Task 9: Update implement-prompt.md template

**Files:**
- Modify: `templates/implement-prompt.md`

- [ ] **Step 1: Replace SPECS_DIR/ISSUE_KEY with SPEC_PATH**

The template currently uses `{{SPECS_DIR}}/{{ISSUE_KEY}}` to reference spec, plan, and tasks files. Replace with `{{SPEC_PATH}}` which will be either a relative path (same repo) or absolute path (workspace repo):

```markdown
You are implementing an approved plan. This is the THIRD stage of Spec-Driven Development.

## JIRA Issue: {{ISSUE_KEY}}
## Specification: {{SPEC_PATH}}/spec.md
## Plan: {{SPEC_PATH}}/plan.md
## Tasks: {{SPEC_PATH}}/tasks.md

## Repository Conventions

Before implementing, check if the repository root contains a `CLAUDE.md` or `AGENT.md` file. If it exists, read it and follow its conventions and instructions.

## Instructions

1. Read the tasks document — it defines the ordered work units
2. Read the plan for technical context and design decisions
3. Read the spec to understand the acceptance criteria you must satisfy
4. Implement each task in the order specified in tasks.md
5. After all tasks, verify each acceptance criterion from the spec
6. **RUN TESTS LOCALLY** — see Testing section below. This is NOT optional. Do not finish without running tests.
7. Fix any test or lint failures found in step 6

## Testing — MANDATORY

You have a Docker runtime available via the `docker` command. You MUST use it to run tests and lint before you finish.

**How to find the right test command:**
1. First check `CLAUDE.md` or `AGENT.md` in the repo root — they often specify exact commands
2. If not found, check the `Makefile` for test/lint targets
3. If not found, check CI config files (`.github/workflows/`, `.prow.yaml`, `.ci-operator/`) to see what CI runs
4. If not found, check `README.md`

**How to run tests with Docker:**
```bash
docker run --rm -v $(pwd):/workspace -w /workspace <language-image> sh -c '<test-commands>'
```

Examples:
- Go: `docker run --rm -v $(pwd):/workspace -w /workspace golang:1.23 sh -c 'make lint && make test'`
- Python: `docker run --rm -v $(pwd):/workspace -w /workspace python:3.12 sh -c 'pip install -r requirements.txt && pytest'`
- Node: `docker run --rm -v $(pwd):/workspace -w /workspace node:20 sh -c 'npm ci && npm test'`

Adapt the image version and commands to match what the project actually uses.

**If tests fail:** fix the code and re-run until they pass.
**If Docker is unavailable** (connection error): note this in your output but continue — this is the only acceptable reason to skip testing.

## Rules

- Follow the task order. Complete each task before moving to the next.
- Follow the plan's design decisions exactly. Do not deviate or add scope.
- Match existing code patterns and conventions in the repository.
- If a task says "test first", write the test before the implementation.
- If you cannot complete a task, leave a TODO comment and continue.
- Commit messages should reference the JIRA issue key: {{ISSUE_KEY}}.

## CI Awareness

After pushing, CI checks (lint, security scans, tests) will run on your changes. Running tests locally first prevents most CI failures:
- Follow the repository's lint configuration (check `.golangci.yml`, `.eslintrc`, etc.)
- Ensure all imports are used and properly ordered
- Handle all errors explicitly — no ignored return values
```

- [ ] **Step 2: Commit**

```bash
git add templates/implement-prompt.md
git commit -m "update implement-prompt template to use SPEC_PATH placeholder"
```

---

### Task 10: Update main.py startup wiring

**Files:**
- Modify: `otto_complete/main.py:1-97`

- [ ] **Step 1: Update imports**

Add `RepoContext` to the config import. Remove `GitHubClient` and `GitClient` from their old import locations if needed — they're now constructed inline:

```python
import logging
import os
import signal
import threading

from otto_complete.config import load_config, RepoContext
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
```

- [ ] **Step 2: Replace single-bot construction with per-watcher context building**

Replace the section that creates `jira`, `github`, `git`, and the three bot instances with per-watcher construction. The new code goes after `set_budget_tracker(budget)` and the `jira = JiraClient(config)` line:

```python
    jira = JiraClient(config)

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

- [ ] **Step 3: Update the polling loop to iterate watcher_bots**

Replace the existing polling loop:

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add otto_complete/main.py
git commit -m "wire up per-watcher RepoContext in main polling loop"
```

---

### Task 11: Verify everything imports cleanly

**Files:** None (verification only)

- [ ] **Step 1: Check Python can import the module**

```bash
cd /home/jianzzha/code/otto-complete && python -c "from otto_complete.config import Config, Watcher, RepoContext; print('config OK')"
```

Expected: `config OK`

- [ ] **Step 2: Check clients import**

```bash
python -c "from otto_complete.clients.git import GitClient; print('git OK')"
python -c "from otto_complete.clients.github import GitHubClient; print('github OK')"
```

Expected: both print OK

- [ ] **Step 3: Check bots import**

```bash
python -c "from otto_complete.bots.base import BaseBot; print('base OK')"
python -c "from otto_complete.bots.specifier import SpecifierBot; print('specifier OK')"
python -c "from otto_complete.bots.planner import PlannerBot; print('planner OK')"
python -c "from otto_complete.bots.implementer import ImplementerBot; print('implementer OK')"
```

Expected: all print OK

- [ ] **Step 4: Check main imports**

```bash
python -c "from otto_complete.main import main; print('main OK')"
```

Expected: `main OK`

- [ ] **Step 5: Check claude_runner imports**

```bash
python -c "from otto_complete.claude_runner import run_claude; print('runner OK')"
```

Expected: `runner OK`
