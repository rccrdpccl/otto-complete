You are implementing an approved plan. This is the THIRD stage of Spec-Driven Development.

## JIRA Issue: {{ISSUE_KEY}}
## Specification: {{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md
## Plan: {{SPECS_DIR}}/{{ISSUE_KEY}}/plan.md
## Tasks: {{SPECS_DIR}}/{{ISSUE_KEY}}/tasks.md

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
