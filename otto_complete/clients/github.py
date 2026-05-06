import json
import logging
import os
import subprocess

from otto_complete.config import Config

log = logging.getLogger(__name__)

BOT_MARKER = "<!-- otto-complete -->"

_gh_auth = None


def set_gh_auth(auth):
    global _gh_auth
    _gh_auth = auth


def _run_gh(*args, **kwargs) -> str:
    env = None
    if _gh_auth is not None:
        env = {**os.environ, "GH_TOKEN": _gh_auth.token}
    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True, timeout=kwargs.get("timeout", 120),
        env=env,
    )
    return result.stdout.strip()


class GitHubClient:
    def __init__(self, config: Config):
        self.repo = config.repo

    def create_pr(self, branch: str, title: str, body: str, base: str = "", labels: str = "") -> str:
        args = ["pr", "create", "--repo", self.repo, "--head", branch, "--title", title, "--body", body]
        if base:
            args += ["--base", base]

        if labels:
            label_args = []
            for label in labels.split(","):
                label_args += ["--label", label.strip()]
            try:
                return _run_gh(*args, *label_args)
            except Exception:
                log.warning("PR creation with labels failed, retrying without")

        return _run_gh(*args)

    def pr_state(self, pr_number: int) -> str:
        return _run_gh("pr", "view", str(pr_number), "--repo", self.repo, "--json", "state", "-q", ".state") or "UNKNOWN"

    def pr_is_merged(self, pr_number: int) -> bool:
        return self.pr_state(pr_number) == "MERGED"

    def find_pr_by_branch(self, branch: str) -> int | None:
        result = _run_gh(
            "pr", "list", "--repo", self.repo, "--head", branch,
            "--state", "all", "--json", "number", "-q", ".[0].number",
        )
        if result and result.isdigit():
            return int(result)
        return None

    def get_review_threads(self, pr_number: int) -> dict:
        owner, name = self.repo.split("/")
        query = '''
        query($owner: String!, $name: String!, $pr: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  comments(first: 50) {
                    nodes {
                      id
                      databaseId
                      body
                      author { login }
                      path
                      line
                    }
                  }
                }
              }
            }
          }
        }'''
        result = _run_gh(
            "api", "graphql",
            "-f", f"query={query}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
            "-F", f"pr={pr_number}",
        )
        return json.loads(result) if result else {}

    def get_pr_comments(self, pr_number: int) -> list[dict]:
        result = _run_gh("api", f"repos/{self.repo}/issues/{pr_number}/comments", "--paginate")
        return json.loads(result) if result else []

    def reply_to_review_comment(self, pr_number: int, comment_id: int, body: str) -> bool:
        body = f"{body}\n\n{BOT_MARKER}"
        try:
            _run_gh(
                "api", f"repos/{self.repo}/pulls/{pr_number}/comments/{comment_id}/replies",
                "-f", f"body={body}",
            )
            return True
        except Exception:
            log.warning("Failed to reply to comment %d", comment_id)
            return False

    def comment_on_pr(self, pr_number: int, body: str) -> bool:
        body = f"{body}\n\n{BOT_MARKER}"
        try:
            _run_gh("api", f"repos/{self.repo}/issues/{pr_number}/comments", "-f", f"body={body}")
            return True
        except Exception:
            log.warning("Failed to comment on PR #%d", pr_number)
            return False

    def resolve_thread(self, thread_id: str) -> bool:
        mutation = '''
        mutation($id: ID!) {
          resolveReviewThread(input: {threadId: $id}) {
            thread { id isResolved }
          }
        }'''
        try:
            _run_gh("api", "graphql", "-f", f"query={mutation}", "-F", f"id={thread_id}")
            return True
        except Exception:
            log.warning("Failed to resolve thread %s", thread_id)
            return False

    def add_reaction(self, comment_id: int, reaction: str = "eyes") -> bool:
        try:
            _run_gh(
                "api", f"repos/{self.repo}/issues/comments/{comment_id}/reactions",
                "-f", f"content={reaction}",
            )
            return True
        except Exception:
            log.warning("Failed to react to comment %d", comment_id)
            return False

    def comment_has_reaction(self, comment_id: int, reaction: str = "eyes") -> bool:
        try:
            result = _run_gh(
                "api", f"repos/{self.repo}/issues/comments/{comment_id}/reactions",
                "--jq", f'[.[] | select(.content == "{reaction}")] | length',
            )
            return int(result or "0") > 0
        except Exception:
            return False

    def get_pr_checks(self, pr_number: int) -> list[dict]:
        result = _run_gh(
            "pr", "checks", str(pr_number), "--repo", self.repo,
            "--json", "name,bucket,state,description,link,completedAt",
        )
        return json.loads(result) if result else []

    def get_failed_checks(self, pr_number: int) -> list[dict]:
        checks = self.get_pr_checks(pr_number)
        return [c for c in checks if c.get("bucket") == "fail"]

    def checks_are_pending(self, pr_number: int) -> bool:
        checks = self.get_pr_checks(pr_number)
        if not checks:
            return True
        skip_names = {"tide", "CodeRabbit", "automerge"}
        return any(
            c.get("bucket") == "pending" and c.get("name") not in skip_names
            for c in checks
        )

    def all_checks_pass(self, pr_number: int) -> bool:
        checks = self.get_pr_checks(pr_number)
        if not checks:
            return False
        skip_names = {"tide", "CodeRabbit", "automerge"}
        return all(
            c.get("bucket") in ("pass", "skipping") or c.get("name") in skip_names
            for c in checks
        )

    def format_failed_checks(self, failed_checks: list[dict]) -> str:
        lines = []
        for c in failed_checks:
            lines.append(f"### Check: {c.get('name', 'unknown')}")
            lines.append(f"- **Status:** {c.get('state', 'unknown')}")
            lines.append(f"- **Description:** {c.get('description') or 'none'}")
            lines.append(f"- **Log URL:** {c.get('link') or 'none'}")
            lines.append("\n---\n")
        return "\n".join(lines) if lines else "No failed check details available."
