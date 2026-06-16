# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

otto-complete is an autonomous JIRA-to-PR pipeline that uses Spec-Driven Development. It polls JIRA for issues labeled `auto-spec`, then drives them through three stages — specification, planning, implementation — each producing a PR for human review. State transitions are tracked via JIRA labels (`ai:specifying` -> `ai:spec-review` -> `ai:planning` -> `ai:plan-review` -> `ai:implementing` -> `ai:impl-review` -> `ai:done`).

The system runs Claude Code headless (`claude -p`) as a subprocess for AI work, with a DinD sidecar for test execution and GitHub App authentication for repo access.

## Running

```bash
# Run locally (needs OTTO_CONFIG pointing to a config YAML)
OTTO_CONFIG=path/to/config.yaml python -m otto_complete

# Build and deploy to kind cluster
./k8s/deploy.sh
```

There is no test suite or linter configured for this project itself. No `setup.py` or `pyproject.toml` — dependencies are in `requirements.txt` and installed directly in the container.

## Commit Message Convention

Format: `ISSUE(scope): message` — e.g., `MGMT-1234(spec): create specification`, `MGMT-1234(plan): address review comments`.

## Architecture

**Polling loop** (`main.py`): Single-threaded loop that iterates over configured watchers, running each bot's `run_pass()` in sequence. Signal handling via `threading.Event` for graceful shutdown.

**Three bots** (`bots/`): All inherit from `BaseBot` which provides template rendering, Claude invocation, and git commit helpers.
- `SpecifierBot`: Picks up new JIRA issues, generates `spec.md`, opens spec PR.
- `PlannerBot`: Waits for spec PR merge, generates `plan.md` + `tasks.md`, opens plan PR.
- `ImplementerBot`: Waits for plan PR merge, implements the plan, opens impl PR, monitors CI, auto-fixes failures (up to 3 attempts), and addresses review comments.

Each bot's `run_pass()` has three sub-passes: recovery (fix stuck labels), normal processing, and review comment handling.

**Claude runner** (`claude_runner.py`): Wraps `claude -p` subprocess calls. Checks global budget before each run, records metrics after. The `--plugin-dir /opt/superpowers` flag loads the superpowers plugin from the container image.

**Clients** (`clients/`):
- `git.py`: Git operations using subprocess. Auth via `x-access-token` URL rewriting for GitHub App tokens.
- `github.py`: GitHub operations via `gh` CLI subprocess. Uses GraphQL for review threads, REST for comments/reactions/checks. `BOT_MARKER` (`<!-- otto-complete -->`) prevents the bot from responding to its own comments.
- `github_auth.py`: GitHub App JWT generation and installation token refresh (auto-refreshes every ~50 min via daemon thread).
- `jira.py`: JIRA REST API v3 client with retry. Label-based state machine operations (`swap_label`, `add_label`, `remove_label`). Handles Atlassian Document Format (ADF) for descriptions and comments.

**Review handling** (`review.py`): Collects unaddressed review comments (skipping bot accounts and already-seen comments marked with `eyes` reaction), formats them for Claude prompts, and posts replies. Auto-resolves threads when code changes address comments.

**Budget** (`budget.py`): Thread-safe cumulative spending tracker. Persists to `.budget.json`. Per-run budget limits are passed to `claude --max-budget-usd`; the global limit gates whether a run starts at all.

**Templates** (`templates/`): Prompt templates using `{{PLACEHOLDER}}` syntax (simple string replacement in `BaseBot.render_template`). Each stage and sub-stage has its own template.

**Config** (`config.py`): Loaded from YAML (default `/etc/otto-complete/config.yaml`, override via `OTTO_CONFIG` env var). Secrets come from environment variables (`JIRA_URL`, `JIRA_USER`, `JIRA_API_TOKEN`, `GITHUB_APP_PRIVATE_KEY_PATH`).

## Key Design Patterns

- **Label-as-state**: All workflow state lives in JIRA labels. Each bot queries for issues at its expected label state and advances them. Recovery passes detect stuck states (e.g., `ai:specifying` with no PR) and either retry or fix labels.
- **Review comment tracking**: Issue comments are marked "seen" via `eyes` reaction. Review thread comments are tracked by thread resolution state. Bot's own comments are identified by `BOT_MARKER`.
- **CI fix loop**: ImplementerBot monitors CI checks, auto-fixes up to `ci_max_retries` times per push cycle. Attempt counter persists to `.ci-attempts-{issue_key}` files. Counter resets when review comments trigger a new push.
- **Flake detection**: CI fix prompt asks Claude to produce `ci-analysis.json` with a `flake` boolean. If true, the bot posts `/retest` instead of code changes.

## Deployment

Runs on Kubernetes (kind cluster) as a single-replica Deployment with Recreate strategy. DinD runs as a restartable init container. Config is mounted from a ConfigMap at `/etc/otto-complete/config.yaml`. Secrets (JIRA creds, GitHub App PEM, GCP SA key) are mounted from separate Secret resources. Uses Vertex AI for Claude access (`CLAUDE_CODE_USE_VERTEX=1`).

## Claude Code Guideline

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical Changes

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

### Goal-Driven Execution

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

