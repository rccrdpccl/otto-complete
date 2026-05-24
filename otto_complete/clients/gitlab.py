import json
import logging
from urllib.parse import quote

import requests

from otto_complete.clients.github import BOT_MARKER

log = logging.getLogger(__name__)


class GitLabClient:
    def __init__(self, repo: str, auth=None, base_url: str = "https://gitlab.com"):
        self.repo = repo
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.project_path = quote(repo, safe="")
        self._last_mr_iid: int | None = None

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}/api/v4{path}"
        headers = kwargs.pop("headers", {})
        if self.auth is not None:
            headers["PRIVATE-TOKEN"] = self.auth.token
        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        resp.raise_for_status()
        return resp

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self._api("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return self._api("POST", path, **kwargs)

    def _put(self, path: str, **kwargs) -> requests.Response:
        return self._api("PUT", path, **kwargs)

    _STATE_MAP = {"opened": "OPEN", "closed": "CLOSED", "merged": "MERGED", "locked": "OPEN"}

    def create_pr(self, branch: str, title: str, body: str, base: str = "", labels: str = "") -> str:
        data = {
            "source_branch": branch,
            "target_branch": base or "main",
            "title": title,
            "description": body,
        }
        if labels:
            data["labels"] = labels
        try:
            resp = self._post(f"/projects/{self.project_path}/merge_requests", json=data)
            mr = resp.json()
            return mr.get("web_url", str(mr.get("iid", "")))
        except Exception:
            log.warning("MR creation with labels failed, retrying without")
            data.pop("labels", None)
            resp = self._post(f"/projects/{self.project_path}/merge_requests", json=data)
            mr = resp.json()
            return mr.get("web_url", str(mr.get("iid", "")))

    def pr_state(self, pr_number: int) -> str:
        try:
            resp = self._get(f"/projects/{self.project_path}/merge_requests/{pr_number}")
            state = resp.json().get("state", "unknown")
            return self._STATE_MAP.get(state, "UNKNOWN")
        except Exception:
            return "UNKNOWN"

    def pr_is_merged(self, pr_number: int) -> bool:
        return self.pr_state(pr_number) == "MERGED"

    def _get_all_pages(self, path: str, **kwargs) -> list:
        results = []
        params = kwargs.pop("params", {})
        params.setdefault("per_page", 100)
        page = 1
        while True:
            params["page"] = page
            resp = self._get(path, params=params, **kwargs)
            data = resp.json()
            if not data:
                break
            results.extend(data)
            if len(data) < params["per_page"]:
                break
            page += 1
        return results

    def get_review_threads(self, pr_number: int) -> dict:
        self._last_mr_iid = pr_number
        try:
            discussions = self._get_all_pages(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/discussions"
            )
        except Exception:
            log.warning("Failed to fetch discussions for MR !%d", pr_number)
            return {}

        threads = []
        for disc in discussions:
            if disc.get("individual_note", False):
                continue
            notes = disc.get("notes", [])
            if not notes:
                continue
            resolvable_notes = [n for n in notes if n.get("resolvable", False)]
            is_resolved = bool(resolvable_notes) and all(n.get("resolved", False) for n in resolvable_notes)

            comment_nodes = []
            for note in notes:
                position = note.get("position") or {}
                comment_nodes.append({
                    "id": str(note["id"]),
                    "databaseId": note["id"],
                    "body": note.get("body", ""),
                    "author": {"login": note.get("author", {}).get("username", "")},
                    "path": position.get("new_path"),
                    "line": position.get("new_line"),
                })

            threads.append({
                "id": disc["id"],
                "isResolved": is_resolved,
                "comments": {"nodes": comment_nodes},
            })

        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": threads
                        }
                    }
                }
            }
        }

    def _find_discussion_for_note(self, pr_number: int, note_id: int) -> str | None:
        try:
            discussions = self._get_all_pages(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/discussions"
            )
            for disc in discussions:
                for note in disc.get("notes", []):
                    if note["id"] == note_id:
                        return disc["id"]
        except Exception:
            log.warning("Failed to find discussion for note %d", note_id)
        return None

    def reply_to_review_comment(self, pr_number: int, comment_id: int, body: str) -> bool:
        body = f"{body}\n\n{BOT_MARKER}"
        discussion_id = self._find_discussion_for_note(pr_number, comment_id)
        if not discussion_id:
            log.warning("Could not find discussion for comment %d", comment_id)
            return False
        try:
            self._post(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/discussions/{discussion_id}/notes",
                json={"body": body},
            )
            return True
        except Exception:
            log.warning("Failed to reply to comment %d", comment_id)
            return False

    def resolve_thread(self, thread_id: str) -> bool:
        if self._last_mr_iid is None:
            log.warning("Cannot resolve thread %s — no MR context", thread_id)
            return False
        try:
            self._put(
                f"/projects/{self.project_path}/merge_requests/{self._last_mr_iid}/discussions/{thread_id}",
                json={"resolved": True},
            )
            return True
        except Exception:
            log.warning("Failed to resolve thread %s", thread_id)
            return False

    def get_pr_comments(self, pr_number: int) -> list[dict]:
        try:
            notes = self._get_all_pages(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/notes",
                params={"sort": "asc"},
            )
        except Exception:
            log.warning("Failed to fetch comments for MR !%d", pr_number)
            return []

        comments = []
        for note in notes:
            if note.get("system", False):
                continue
            author = note.get("author", {})
            comments.append({
                "id": note["id"],
                "body": note.get("body", ""),
                "user": {
                    "login": author.get("username", ""),
                    "type": "Bot" if "bot" in author.get("username", "").lower() else "User",
                },
            })
        return comments

    def comment_on_pr(self, pr_number: int, body: str) -> bool:
        body = f"{body}\n\n{BOT_MARKER}"
        try:
            self._post(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/notes",
                json={"body": body},
            )
            return True
        except Exception:
            log.warning("Failed to comment on MR !%d", pr_number)
            return False

    def add_reaction(self, comment_id: int, reaction: str = "eyes") -> bool:
        if self._last_mr_iid is None:
            log.warning("Cannot add reaction — no MR context")
            return False
        try:
            self._post(
                f"/projects/{self.project_path}/merge_requests/{self._last_mr_iid}/notes/{comment_id}/award_emoji",
                json={"name": reaction},
            )
            return True
        except Exception:
            log.warning("Failed to react to comment %d", comment_id)
            return False

    def comment_has_reaction(self, comment_id: int, reaction: str = "eyes") -> bool:
        if self._last_mr_iid is None:
            return False
        try:
            resp = self._get(
                f"/projects/{self.project_path}/merge_requests/{self._last_mr_iid}/notes/{comment_id}/award_emoji"
            )
            emojis = resp.json()
            return any(e.get("name") == reaction for e in emojis)
        except Exception:
            return False

    def find_pr_by_branch(self, branch: str) -> int | None:
        try:
            resp = self._get(
                f"/projects/{self.project_path}/merge_requests",
                params={"source_branch": branch, "state": "all", "per_page": 1},
            )
            mrs = resp.json()
            if mrs:
                return mrs[0]["iid"]
        except Exception:
            log.warning("Failed to find MR for branch %s", branch)
        return None
