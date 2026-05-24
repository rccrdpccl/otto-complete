You are addressing review comments on an implementation PR. Your goal is to evaluate each comment and either update the code or explain why no change is needed.

## JIRA Issue: {{ISSUE_KEY}}

## Context

The spec is at `{{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md` and the plan at `{{SPECS_DIR}}/{{ISSUE_KEY}}/plan.md`. Read them for context.

{{SOURCE_REPOS}}

## Review Comments to Address

{{COMMENTS}}

## Instructions

For each comment above:

1. **Evaluate** whether the feedback is valid and actionable
2. If valid: **edit** the relevant source files to address it
3. If not valid or already covered: prepare a reply explaining why

After processing all comments, write a JSON file to `{{SPECS_DIR}}/{{ISSUE_KEY}}/review-replies.json` with this exact format:

```json
[
  {
    "comment_id": <the numeric comment ID>,
    "type": "review or issue (match the type shown in the comment header)",
    "reply": "Your reply text explaining what you changed or why no change is needed",
    "resolved": true
  }
]
```

- The `type` field must match what's shown in each comment header (`review` for inline code comments, `issue` for general PR comments).
- Set `"resolved": false` only if you are genuinely unsure and want the human to decide. Only applies to `review` type.

## Rules

- Be respectful but direct. You can disagree — explain your reasoning.
- Fix real bugs and valid code review feedback.
- If a comment is about style preference with no functional impact, push back politely.
- Do not introduce regressions when fixing review comments.
- **MANDATORY**: You MUST write the `review-replies.json` file for EVERY comment, no exceptions. Each comment must get a reply explaining what you changed OR why no change is needed. A reviewer should NEVER be left without a response.
- Even if you made code changes that fully address the comment, write a reply confirming what you did.
