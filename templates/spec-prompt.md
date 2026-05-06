You are writing a formal specification for a JIRA issue. This is the FIRST stage of Spec-Driven Development — you define WHAT needs to be built and WHY, without any implementation details.

## JIRA Issue: {{ISSUE_KEY}}
**Summary:** {{SUMMARY}}

**Description:**
{{DESCRIPTION}}

## Instructions

1. Read the JIRA issue carefully
2. Explore the codebase to understand the current state of the relevant components
3. Write a specification document to {{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md

## Specification Format

The spec.md must contain these sections:

### Overview
One paragraph: what this feature/change does and why it matters.

### User Stories
Who benefits and how. Use the format:
- As a [role], I want [capability], so that [benefit].

### Requirements
Numbered list of concrete, testable requirements. Each must be unambiguous and measurable.
Mark anything unclear with `[NEEDS CLARIFICATION]`.

### Acceptance Criteria
Bullet list of conditions that must be true for this work to be considered done.
These should be verifiable by a reviewer or automated test.

### Non-Functional Requirements
Performance, security, backward compatibility, or operational constraints (if any).

### Out of Scope
Explicitly list what this change does NOT cover, to prevent scope creep.

### Open Questions
List anything that needs human input before planning can begin.

## Rules

- Focus ONLY on WHAT and WHY — never HOW.
- No code, no file paths, no API designs, no architecture decisions.
- Be specific enough that a different person (or AI) could write the implementation plan from this spec alone.
- If the JIRA description is vague, state assumptions and mark them with `[ASSUMPTION]`.
