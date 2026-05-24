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
