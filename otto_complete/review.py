import json
import logging
import os
import re

from otto_complete.clients.github import GitHubClient, BOT_MARKER

log = logging.getLogger(__name__)

BOT_ACCOUNT_PATTERN = re.compile(r"\[bot\]$|^(coderabbitai|openshift-ci-robot|openshift-merge-robot)$")


def collect_unaddressed_comments(github: GitHubClient, pr_number: int) -> list[dict]:
    threads_data = github.get_review_threads(pr_number)
    review_comments = []

    try:
        threads = threads_data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        for thread in threads:
            if thread.get("isResolved"):
                continue
            comments = thread.get("comments", {}).get("nodes", [])
            if not comments:
                continue
            last = comments[-1]
            body = last.get("body", "")
            author = last.get("author", {}).get("login", "")
            if BOT_MARKER in body:
                continue
            if BOT_ACCOUNT_PATTERN.search(author):
                continue
            review_comments.append({
                "type": "review",
                "threadId": thread["id"],
                "comment_id": last.get("databaseId"),
                "body": body,
                "author": author,
                "path": last.get("path"),
                "line": last.get("line"),
            })
    except (KeyError, TypeError):
        pass

    issue_comments_raw = github.get_pr_comments(pr_number)
    issue_comments = []
    for c in issue_comments_raw:
        body = c.get("body", "")
        user = c.get("user", {})
        if BOT_MARKER in body:
            continue
        if user.get("type") == "Bot":
            continue
        login = user.get("login", "")
        if re.match(r"^(openshift-ci-robot|openshift-merge-robot)$", login):
            continue
        issue_comments.append({
            "type": "issue",
            "comment_id": c.get("id"),
            "body": body,
            "author": login,
        })

    filtered_issue = []
    for ic in issue_comments:
        if not github.comment_has_reaction(ic["comment_id"], "eyes"):
            filtered_issue.append(ic)

    return review_comments + filtered_issue


def format_comments_for_prompt(comments: list[dict]) -> str:
    if not comments:
        return "No comments to process."
    lines = []
    for c in comments:
        header = f"### Comment ID: {c['comment_id']} (by @{c['author']}) [type: {c['type']}]"
        lines.append(header)
        if c.get("path"):
            loc = f"**File:** `{c['path']}`"
            if c.get("line"):
                loc += f" line {c['line']}"
            lines.append(loc)
        lines.append(c["body"])
        lines.append("\n---\n")
    return "\n".join(lines)


def post_review_replies(
    github: GitHubClient,
    issue_key: str,
    pr_number: int,
    original_comments: list[dict],
    replies_file: str,
    has_changes: bool = True,
):
    if not os.path.isfile(replies_file):
        log.warning("%s: no review-replies.json produced", issue_key)
        if has_changes:
            auto_resolve_review_threads(github, pr_number, original_comments)
        else:
            _post_fallback_replies(github, pr_number, original_comments)
        mark_issue_comments_seen(github, original_comments)
        return

    with open(replies_file) as f:
        replies = json.load(f)

    log.info("%s: posting %d review replies", issue_key, len(replies))

    threads_data = github.get_review_threads(pr_number)

    for reply_item in replies:
        comment_id = reply_item.get("comment_id")
        reply_body = reply_item.get("reply")
        resolved = reply_item.get("resolved", True)
        comment_type = reply_item.get("type", "review")

        if comment_type == "issue":
            if reply_body and reply_body != "null":
                github.comment_on_pr(pr_number, reply_body)
            github.add_reaction(comment_id, "eyes")
        else:
            if reply_body and reply_body != "null":
                github.reply_to_review_comment(pr_number, comment_id, reply_body)
            if resolved:
                thread_id = _find_thread_id(threads_data, comment_id)
                if thread_id:
                    github.resolve_thread(thread_id)

    os.remove(replies_file)
    mark_issue_comments_seen(github, original_comments)


def auto_resolve_review_threads(github: GitHubClient, pr_number: int, original_comments: list[dict]):
    if not original_comments:
        return

    review_comments = [c for c in original_comments if c["type"] == "review"]
    if not review_comments:
        return

    threads_data = github.get_review_threads(pr_number)

    for c in review_comments:
        comment_id = c["comment_id"]
        github.reply_to_review_comment(pr_number, comment_id, "Addressed in latest commit.")
        thread_id = _find_thread_id(threads_data, comment_id)
        if thread_id:
            github.resolve_thread(thread_id)


def mark_issue_comments_seen(github: GitHubClient, comments: list[dict]):
    if not comments:
        return
    for c in comments:
        if c["type"] == "issue":
            github.add_reaction(c["comment_id"], "eyes")


def _post_fallback_replies(github: GitHubClient, pr_number: int, comments: list[dict]):
    fallback_msg = f"Acknowledged — I reviewed this feedback but could not determine how to address it with code changes. Leaving for maintainer review.\n\n{BOT_MARKER}"
    threads_data = None
    for c in comments:
        if c["type"] == "review":
            github.reply_to_review_comment(pr_number, c["comment_id"], fallback_msg)
            if threads_data is None:
                threads_data = github.get_review_threads(pr_number)
            thread_id = _find_thread_id(threads_data, c["comment_id"])
        elif c["type"] == "issue":
            github.comment_on_pr(pr_number, fallback_msg)
    log.info("Posted fallback replies to %d comments on PR #%d", len(comments), pr_number)


def _find_thread_id(threads_data: dict, comment_id: int) -> str | None:
    try:
        threads = threads_data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        for thread in threads:
            for comment in thread.get("comments", {}).get("nodes", []):
                if comment.get("databaseId") == comment_id:
                    return thread["id"]
    except (KeyError, TypeError):
        pass
    return None
