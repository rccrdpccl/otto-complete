# otto-complete

Autonomous JIRA-to-PR pipeline using Spec-Driven Development. A single Python deployment with three bots and an internal polling loop.

## How It Works

```
JIRA issue (label: auto-spec)
    │
    ▼
┌──────────┐  ai:specifying → ai:spec-review
│ Specifier │──→ Reads JIRA issue, generates spec.md, opens spec PR
└──────────┘
    │  Human reviews & merges spec PR
    ▼
┌──────────┐  ai:planning → ai:plan-review
│ Planner  │──→ Generates plan.md + tasks.md, opens plan PR
└──────────┘
    │  Human reviews & merges plan PR
    ▼
┌──────────┐  ai:implementing → ai:impl-review → ai:done
│Implementer│──→ Implements tasks, opens impl PR, monitors CI, addresses reviews
└──────────┘
```

Each stage produces a PR requiring human review. All state is tracked via JIRA labels.

## Architecture

- **Single Deployment** with internal polling loop (configurable interval)
- **Claude Code** (`claude -p`) as the AI engine in headless mode
- **GitHub App** authentication (no personal tokens)
- **DinD sidecar** for local test execution via Docker
- **Prometheus metrics** on `:9090`
- **Global budget tracker** — cumulative USD limit across all Claude runs

## Setup

### 1. GitHub App

Create a GitHub App with these **repository** permissions:

| Permission | Access |
|-----------|--------|
| Contents | Read & Write |
| Pull requests | Read & Write |
| Issues | Read & Write |
| Checks | Read |
| Metadata | Read |

No webhooks needed. Install on target repo(s).

### 2. Configuration

Edit `k8s/configmap.yaml`:

```yaml
repo: your-org/your-repo
clone_url: https://github.com/your-org/your-repo.git
github_app_id: "123456"
github_app_installation_id: "789012"
label: auto-spec
poll_interval: 120
max_total_budget_usd: 50.00
watchers:
  - project: MYPROJECT
    component: "My Component"
```

### 3. Secrets

Copy and fill `k8s/secrets.yaml.example` → `k8s/secrets.yaml`:

- JIRA API token, URL, user
- GitHub App private key (PEM)
- GCP service account key (for Vertex AI / Claude)

**Never commit `k8s/secrets.yaml`** — it's in `.gitignore`.

### 4. Deploy

```bash
./k8s/deploy.sh
```

Builds the image, creates a kind cluster, and applies all manifests.

## Project Structure

```
otto_complete/
├── main.py              # Polling loop, signal handling, init
├── config.py            # YAML config loading
├── claude_runner.py     # Claude CLI wrapper with budget checks
├── budget.py            # Global spending tracker (persistent)
├── metrics.py           # Prometheus counters/histograms
├── review.py            # PR review comment handling
├── logging_setup.py     # Structured logging
├── clients/
│   ├── git.py           # Git operations (HTTPS + token auth)
│   ├── github.py        # GitHub CLI wrapper
│   ├── github_auth.py   # GitHub App JWT + installation token
│   └── jira.py          # JIRA REST API v3 client
└── bots/
    ├── base.py          # Base bot with template rendering
    ├── specifier.py     # Spec generation bot
    ├── planner.py       # Plan generation bot
    └── implementer.py   # Implementation + CI fix + review bot
templates/               # Prompt templates for each stage
k8s/                     # Kubernetes manifests
```

## JIRA Label State Machine

```
auto-spec → ai:specifying → ai:spec-review → ai:planning → ai:plan-review
    → ai:implementing → ai:impl-review ⟲ ai:ci-fixing → ai:done
```

On failure: `ai:error` (auto-recovers if open PR exists).

## Budget

Per-run limits in config (`max_budget_spec`, `max_budget_impl`, etc.) plus a global cumulative limit (`max_total_budget_usd`). Budget state persists to disk. When exhausted, all Claude runs are skipped until the state file is reset or the limit is raised.

## Troubleshooting

- **Issue not picked up**: Check JIRA label — needs `auto-spec` and no `ai:*` label yet.
- **Stuck on `ai:error`**: Bot auto-recovers if an open PR exists. Otherwise, fix the issue and manually set the label back.
- **CI fix loop**: Max 3 auto-fix attempts per push cycle. Resets when review comments trigger a new push.
- **Budget exhausted**: Check logs for "Global budget exhausted". Reset `.budget.json` in the work dir or raise the limit.
