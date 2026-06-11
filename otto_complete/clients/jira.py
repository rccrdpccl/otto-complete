import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from otto_complete.config import Config

log = logging.getLogger(__name__)

AI_LABELS = [
    "ai:specifying", "ai:spec-review",
    "ai:planning", "ai:plan-review",
    "ai:implementing", "ai:impl-review",
    "ai:ci-fixing", "ai:done", "ai:error",
]


class JiraClient:
    def __init__(self, config: Config):
        self.url = config.jira_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (config.jira_user, config.jira_api_token)
        self.session.headers["Content-Type"] = "application/json"

        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def _search(self, jql: str) -> list[str]:
        resp = self.session.get(
            f"{self.url}/rest/api/3/search/jql",
            params={"jql": jql, "fields": "key", "maxResults": 100},
        )
        resp.raise_for_status()
        return [issue["key"] for issue in resp.json().get("issues", [])]

    def _component_jql(self, component: str) -> str:
        if component:
            return f' AND component = "{component}"'
        return ""

    def query_new_issues(self, project: str, label: str, component: str = "") -> list[str]:
        exclude = " ".join(f'AND labels != "{l}"' for l in AI_LABELS)
        jql = (
            f'project = "{project}" AND labels = "{label}" '
            f'{exclude} AND status not in (Done, Closed, Resolved)'
            f'{self._component_jql(component)}'
        )
        return self._search(jql)

    def query_by_label(self, project: str, label: str, component: str = "") -> list[str]:
        jql = (
            f'project = "{project}" AND labels = "{label}"'
            f' AND status not in (Done, Closed, Resolved)'
            f'{self._component_jql(component)}'
        )
        return self._search(jql)

    def get_summary(self, issue_key: str) -> str:
        resp = self.session.get(f"{self.url}/rest/api/3/issue/{issue_key}", params={"fields": "summary"})
        resp.raise_for_status()
        return resp.json()["fields"].get("summary", "")

    def get_description(self, issue_key: str) -> str:
        resp = self.session.get(f"{self.url}/rest/api/3/issue/{issue_key}", params={"fields": "description"})
        resp.raise_for_status()
        desc = resp.json()["fields"].get("description")
        if isinstance(desc, dict):
            return self._extract_adf_text(desc)
        return desc or ""

    def get_details(self, issue_key: str) -> tuple[str, str]:
        resp = self.session.get(
            f"{self.url}/rest/api/3/issue/{issue_key}",
            params={"fields": "summary,description"},
        )
        resp.raise_for_status()
        fields = resp.json()["fields"]
        desc = fields.get("description")
        if isinstance(desc, dict):
            desc = self._extract_adf_text(desc)
        return fields.get("summary", ""), desc or ""

    def _get_labels(self, issue_key: str) -> list[str]:
        resp = self.session.get(f"{self.url}/rest/api/3/issue/{issue_key}", params={"fields": "labels"})
        resp.raise_for_status()
        return resp.json()["fields"].get("labels", [])

    def _set_labels(self, issue_key: str, labels: list[str]):
        resp = self.session.put(
            f"{self.url}/rest/api/3/issue/{issue_key}",
            json={"fields": {"labels": labels}},
        )
        resp.raise_for_status()

    def add_label(self, issue_key: str, label: str) -> bool:
        try:
            labels = self._get_labels(issue_key)
            if label not in labels:
                labels.append(label)
                self._set_labels(issue_key, labels)
            return True
        except Exception:
            log.warning("Failed to add label '%s' to %s", label, issue_key)
            return False

    def remove_label(self, issue_key: str, label: str) -> bool:
        try:
            labels = self._get_labels(issue_key)
            if label in labels:
                labels.remove(label)
                self._set_labels(issue_key, labels)
            return True
        except Exception:
            log.warning("Failed to remove label '%s' from %s", label, issue_key)
            return False

    def swap_label(self, issue_key: str, old_label: str, new_label: str) -> bool:
        try:
            labels = self._get_labels(issue_key)
            if old_label and old_label in labels:
                labels.remove(old_label)
            if new_label not in labels:
                labels.append(new_label)
            self._set_labels(issue_key, labels)
            return True
        except Exception:
            log.warning("Failed to swap label '%s' -> '%s' on %s", old_label, new_label, issue_key)
            return False

    def add_comment(self, issue_key: str, body: str):
        try:
            adf_body = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": body}]}],
            }
            self.session.post(
                f"{self.url}/rest/api/3/issue/{issue_key}/comment",
                json={"body": adf_body},
            )
        except Exception:
            log.warning("Failed to add JIRA comment to %s", issue_key)

    def transition(self, issue_key: str, status_name: str):
        try:
            resp = self.session.get(f"{self.url}/rest/api/3/issue/{issue_key}/transitions")
            resp.raise_for_status()
            transitions = resp.json().get("transitions", [])
            for t in transitions:
                if t["name"].lower() == status_name.lower():
                    self.session.post(
                        f"{self.url}/rest/api/3/issue/{issue_key}/transitions",
                        json={"transition": {"id": t["id"]}},
                    )
                    return
            log.warning("Transition '%s' not found for %s", status_name, issue_key)
        except Exception:
            log.warning("Failed to transition %s to '%s'", issue_key, status_name)

    def _extract_adf_text(self, node) -> str:
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            text = node.get("text", "")
            for child in node.get("content", []):
                text += self._extract_adf_text(child)
            return text
        if isinstance(node, list):
            return "".join(self._extract_adf_text(item) for item in node)
        return ""

    def count_comments_matching(self, issue_key: str, pattern: str) -> int:
        try:
            resp = self.session.get(
                f"{self.url}/rest/api/3/issue/{issue_key}",
                params={"fields": "comment"},
            )
            resp.raise_for_status()
            comments = resp.json()["fields"].get("comment", {}).get("comments", [])
            count = 0
            regex = re.compile(pattern, re.IGNORECASE)
            for comment in comments:
                body = comment.get("body", "")
                if isinstance(body, dict):
                    body = self._extract_adf_text(body)
                if regex.search(body):
                    count += 1
            return count
        except Exception:
            log.warning("Failed to count comments for %s", issue_key)
            return 0
