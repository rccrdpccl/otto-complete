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
