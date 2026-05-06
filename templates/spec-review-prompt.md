You are addressing review comments on a specification PR. Your goal is to evaluate each comment and either update the spec or explain why no change is needed.

## JIRA Issue: {{ISSUE_KEY}}

## Current Specification

The spec is at `{{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md`. Read it first.

## Review Comments to Address

{{COMMENTS}}

## Instructions

For each comment above:

1. **Evaluate** whether the feedback is valid and actionable
2. If valid: **edit** `{{SPECS_DIR}}/{{ISSUE_KEY}}/spec.md` to address it
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
- If a comment asks for implementation details (HOW), push back — the spec covers WHAT and WHY only.
- If a comment reveals a genuine gap, fix the spec.
- Do not add unnecessary complexity to satisfy a comment — keep the spec focused.
- Always write the review-replies.json file, even if you addressed everything via spec edits.
