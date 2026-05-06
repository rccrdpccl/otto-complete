You are addressing review comments on an implementation plan PR. Your goal is to evaluate each comment and either update the plan/tasks or explain why no change is needed.

## JIRA Issue: {{ISSUE_KEY}}

## Current Plan

The plan is at `{{SPECS_DIR}}/{{ISSUE_KEY}}/plan.md` and tasks at `{{SPECS_DIR}}/{{ISSUE_KEY}}/tasks.md`. Read them first.

## Review Comments to Address

{{COMMENTS}}

## Instructions

For each comment above:

1. **Evaluate** whether the feedback is valid and actionable
2. If valid: **edit** the plan or tasks files to address it
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
- If a comment asks for implementation details beyond the plan scope, push back.
- If a comment reveals a genuine gap in the plan, fix it.
- Do not add unnecessary complexity — keep the plan focused and actionable.
- Always write the review-replies.json file, even if you addressed everything via edits.
