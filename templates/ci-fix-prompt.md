You are fixing CI failures on an implementation PR. Analyze the failures and either fix the code or determine the failure is a flake.

## JIRA Issue: {{ISSUE_KEY}}
## PR Number: {{PR_NUMBER}}
## Fix Attempt: {{ATTEMPT_NUMBER}} of {{MAX_ATTEMPTS}}

## Context

The spec is at `{{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md` and the plan at `{{SPECS_DIR}}/{{ISSUE_KEY}}/plan.md`. Read them for context.

## Failed CI Checks

{{FAILED_CHECKS}}

## Log URLs

Use `curl -sL <url> | head -1000` to fetch detailed CI logs:

{{LOG_URLS}}

## Instructions

1. **Examine the failures**: Read check names, descriptions, and log URLs above
2. **Fetch detailed logs**: Use `curl -sL <url>` on log URLs to get full error output
3. **Determine the cause**:
   - **Code issue** you can fix: lint error, compile error, test failure due to a bug in this PR
   - **Flake / infrastructure issue**: network timeout, registry unavailable, intermittent test failure unrelated to this PR's changes, dependency vulnerability
4. **Fix or flag**:
   - Code issue → edit the relevant source files to fix it
   - Flake → do NOT modify code

5. **Write analysis**: Write `{{SPECS_DIR}}/{{ISSUE_KEY}}/ci-analysis.json`:

```json
{
  "flake": false,
  "fixed": true,
  "summary": "Brief description of what failed and what you did"
}
```

- `flake`: true if the failure is not caused by code in this PR
- `fixed`: true if you made code changes to fix the issue
- `summary`: one-sentence description for the JIRA comment

## Verify Your Fix Locally (MANDATORY)

After fixing the code, you MUST run tests locally via Docker before finishing:
```bash
docker run --rm -v $(pwd):/workspace -w /workspace <language-image> sh -c '<test-commands>'
```
Check CLAUDE.md or Makefile for the exact commands. Only skip if Docker is unreachable (connection error).

## Important
- You CAN use `curl` to fetch log content from URLs.
- You CAN read and edit any source files in the repository.
- Common fixable issues: lint violations, missing nil checks, import ordering, unused variables, type mismatches, missing error handling.
- If a check is about a dependency vulnerability (security/snyk/trivy), mark as flake — this PR does not control upstream dependencies.
- If the error is ambiguous, prefer attempting a fix over marking as flake.
- Always write ci-analysis.json, even if you cannot fix the issue.

## Rules

- Do NOT add `//nolint` or skip directives unless absolutely necessary.
- Match existing code patterns and conventions.
- Check for CLAUDE.md or AGENT.md in the repo root and follow its conventions.
- Keep changes minimal — fix only what CI requires.
