You are creating an implementation plan from an approved specification. This is the SECOND stage of Spec-Driven Development — you define HOW to build what the spec describes.

## JIRA Issue: {{ISSUE_KEY}}
## Approved Specification: {{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md

## Instructions

1. Read the specification document carefully — it is the source of truth for WHAT to build
2. Explore the codebase to understand existing patterns, conventions, and architecture
3. Write TWO documents:
   - `{{SPECS_DIR}}/{{ISSUE_KEY}}/plan.md` — technical implementation plan
   - `{{SPECS_DIR}}/{{ISSUE_KEY}}/tasks.md` — ordered task breakdown

## Plan Format (plan.md)

### Spec Summary
Brief restatement of what the spec requires (1-3 sentences, for traceability).

### Approach
High-level technical strategy. Key design decisions and why.

### Changes
For each file to modify or create:
- **File path** — what changes and why
- Reference existing functions/patterns to reuse

### Data Model Changes
Schema changes, new types, migration needs (if any). Skip if not applicable.

### API Changes
New or modified endpoints, request/response shapes (if any). Skip if not applicable.

### Testing Strategy
What tests to write or update. Which acceptance criteria map to which tests.

### Risks
What could go wrong. Backward compatibility concerns. Migration risks.

## Tasks Format (tasks.md)

Ordered list of concrete work units. Format:

```
## Tasks

- [ ] 1. [Description of task]
  - Files: [file paths]
  - Depends on: [task numbers, or "none"]
  - Test: [how to verify this task alone]

- [ ] 2. [Next task]
  ...
```

### Task ordering rules:
- Tests before implementation when possible (test-first)
- Data model / schema changes before code that uses them
- Mark independent tasks with `[P]` (parallelizable)
- Each task should be completable in isolation and verifiable

## Rules

- Every plan decision must trace back to a spec requirement
- Do NOT implement any code — only produce plan.md and tasks.md
- Be specific — name exact files, functions, types, and line ranges
- Prefer modifying existing code over creating new abstractions
