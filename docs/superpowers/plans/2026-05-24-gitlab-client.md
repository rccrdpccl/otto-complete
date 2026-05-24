# Phase 2: GitLab Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GitLabClient` as a full `CodePlatform` implementation using the GitLab REST API v4 via HTTP requests, achieving parity with `GitHubClient` for MR lifecycle, reviews, CI checks, and reactions.

**Architecture:** `GitLabClient` uses Python `requests` library to call the GitLab REST API v4. It transforms GitLab's native data structures (Merge Requests, Discussions, Pipelines, Award Emoji) into the same shapes that `review.py` and the bots expect from `GitHubClient`. The `repo` field uses GitLab's URL-encoded project path (e.g., `group%2Frepo`). Auth is via `PRIVATE-TOKEN` header using the injected `AuthProvider`.

**Tech Stack:** Python 3.11+, `requests` library, GitLab REST API v4

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `otto_complete/clients/gitlab.py` | `GitLabClient` implementing `CodePlatform` via GitLab REST API |
| Create | `tests/test_gitlab.py` | Unit tests for `GitLabClient` using mocked HTTP responses |
| Modify | `otto_complete/main.py:10,65-69` | Import `GitLabClient`, instantiate for `platform: gitlab` watchers |
| Modify | `otto_complete/review.py:6` | Import `BOT_MARKER` from a shared location (not `github.py`) |
| Modify | `otto_complete/clients/github.py:8` | Keep `BOT_MARKER` but also export from a shared location |

---

## Critical Data Structure Contract

`review.py` and the bots consume data from `CodePlatform` methods. The `GitLabClient` must return data in the **exact same shapes** as `GitHubClient` so these consumers work unchanged.

### `get_review_threads()` must return:
```python
{
    "data": {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "nodes": [
                        {
                            "id": "<discussion_id>",       # GitLab discussion.id
                            "isResolved": bool,             # all notes resolved?
                            "comments": {
                                "nodes": [
                                    {
                                        "id": "<note_id_str>",
                                        "databaseId": int,  # note.id (int)
                                        "body": str,
                                        "author": {"login": str},  # note.author.username
                                        "path": str | None,        # position.new_path
                                        "line": int | None,        # position.new_line
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }
}
```

### `get_pr_comments()` must return:
```python
[
    {
        "body": str,
        "user": {"type": "Bot" | "User", "login": str},  # author.username
        "id": int,  # note.id
    }
]
```

### `get_pr_checks()` must return:
```python
[
    {
        "name": str,          # job.name
        "bucket": str,        # "pass" | "fail" | "pending" | "skipping"
        "state": str,         # job.status
        "description": str,   # job.stage or ""
        "link": str,          # job.web_url
        "completedAt": str,   # job.finished_at or ""
    }
]
```

---

### Task 1: Create GitLabClient Skeleton with HTTP Helper

**Files:**
- Create: `otto_complete/clients/gitlab.py`
- Create: `tests/test_gitlab.py`

- [ ] **Step 1: Write initial test**

```python
# tests/test_gitlab.py
from unittest.mock import patch, MagicMock
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.clients.auth import PatAuth


def test_gitlab_client_init():
    auth = PatAuth("glpat-test123")
    client = GitLabClient("mygroup/myrepo", auth=auth, base_url="https://gitlab.com")
    assert client.repo == "mygroup/myrepo"
    assert client.project_path == "mygroup%2Fmyrepo"
    assert client.base_url == "https://gitlab.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gitlab.py::test_gitlab_client_init -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create gitlab.py with constructor and HTTP helper**

```python
# otto_complete/clients/gitlab.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gitlab.py::test_gitlab_client_init -v`
Expected: PASS

- [ ] **Step 5: Add test for _api method**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_api_sends_auth_header(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_request.return_value = mock_response

    auth = PatAuth("glpat-secret")
    client = GitLabClient("mygroup/myrepo", auth=auth)
    client._get("/projects/mygroup%2Fmyrepo")

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    assert call_kwargs[1]["headers"]["PRIVATE-TOKEN"] == "glpat-secret"
```

- [ ] **Step 6: Run test**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS — 2 tests

- [ ] **Step 7: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient skeleton with HTTP helper and auth"
```

---

### Task 2: MR Lifecycle Methods (create_pr, pr_state, pr_is_merged, find_pr_by_branch)

**Files:**
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `tests/test_gitlab.py`

- [ ] **Step 1: Write tests for MR lifecycle**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_create_pr(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"web_url": "https://gitlab.com/g/r/-/merge_requests/42", "iid": 42}
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    result = client.create_pr("feature-branch", "My MR Title", "MR body", base="main", labels="bug,enhancement")

    mock_request.assert_called_once()
    call_args = mock_request.call_args
    assert call_args[0][0] == "POST"
    assert "/merge_requests" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["source_branch"] == "feature-branch"
    assert body["target_branch"] == "main"
    assert body["title"] == "My MR Title"
    assert body["description"] == "MR body"
    assert body["labels"] == "bug,enhancement"
    assert "42" in result


@patch("otto_complete.clients.gitlab.requests.request")
def test_pr_state(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"state": "merged"}
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    state = client.pr_state(42)
    assert state == "MERGED"


@patch("otto_complete.clients.gitlab.requests.request")
def test_pr_state_open(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"state": "opened"}
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    state = client.pr_state(42)
    assert state == "OPEN"


@patch("otto_complete.clients.gitlab.requests.request")
def test_pr_is_merged(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"state": "merged"}
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    assert client.pr_is_merged(42) is True


@patch("otto_complete.clients.gitlab.requests.request")
def test_find_pr_by_branch(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"iid": 99}]
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    result = client.find_pr_by_branch("feature-x")
    assert result == 99


@patch("otto_complete.clients.gitlab.requests.request")
def test_find_pr_by_branch_not_found(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = []
    mock_request.return_value = mock_response

    client = GitLabClient("mygroup/myrepo", auth=PatAuth("token"))
    result = client.find_pr_by_branch("nonexistent")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: FAIL — `GitLabClient` has no `create_pr` method

- [ ] **Step 3: Implement MR lifecycle methods**

Add to `GitLabClient` in `otto_complete/clients/gitlab.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS — all 8 tests

- [ ] **Step 5: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient MR lifecycle methods"
```

---

### Task 3: Review Thread Methods (get_review_threads, reply_to_review_comment, resolve_thread)

**Files:**
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `tests/test_gitlab.py`

The critical contract: `get_review_threads()` must return data in the exact GitHub GraphQL shape that `review.py` expects. GitLab uses Discussions API — each discussion has notes. We transform:
- GitLab `discussion.id` → thread `id`
- GitLab `note.resolved` → aggregate into thread `isResolved` (all notes resolved)
- GitLab `note.id` → `databaseId` (int)
- GitLab `note.author.username` → `author.login`
- GitLab `note.position.new_path` → `path`
- GitLab `note.position.new_line` → `line`

For `reply_to_review_comment`, we need to find which discussion contains the comment (note) to post a reply. The `comment_id` parameter is the note `databaseId`. We need to map it back to a discussion ID.

For `resolve_thread`, the `thread_id` parameter is the discussion ID.

- [ ] **Step 1: Write tests**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_get_review_threads(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {
            "id": "disc-abc",
            "individual_note": False,
            "notes": [
                {
                    "id": 1001,
                    "body": "Please fix this",
                    "author": {"username": "reviewer1"},
                    "resolved": False,
                    "resolvable": True,
                    "type": "DiffNote",
                    "position": {"new_path": "src/main.py", "new_line": 42},
                }
            ],
        },
        {
            "id": "disc-def",
            "individual_note": True,
            "notes": [{"id": 1002, "body": "general note", "author": {"username": "user2"},
                        "resolved": False, "resolvable": False, "type": None}],
        },
    ]
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    result = client.get_review_threads(10)

    threads = result["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    assert len(threads) == 1  # individual_note filtered out
    t = threads[0]
    assert t["id"] == "disc-abc"
    assert t["isResolved"] is False
    c = t["comments"]["nodes"][0]
    assert c["databaseId"] == 1001
    assert c["author"]["login"] == "reviewer1"
    assert c["path"] == "src/main.py"
    assert c["line"] == 42


@patch("otto_complete.clients.gitlab.requests.request")
def test_reply_to_review_comment(mock_request):
    # First call: list discussions to find the one containing comment_id 1001
    disc_response = MagicMock()
    disc_response.raise_for_status = MagicMock()
    disc_response.json.return_value = [
        {"id": "disc-abc", "notes": [{"id": 1001}]},
        {"id": "disc-def", "notes": [{"id": 1002}]},
    ]

    # Second call: post reply
    reply_response = MagicMock()
    reply_response.raise_for_status = MagicMock()
    reply_response.json.return_value = {"id": 2001}

    mock_request.side_effect = [disc_response, reply_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    result = client.reply_to_review_comment(10, 1001, "Fixed!")
    assert result is True

    # Verify the reply was posted to the correct discussion
    reply_call = mock_request.call_args_list[1]
    assert "disc-abc" in reply_call[0][1]
    assert BOT_MARKER in reply_call[1]["json"]["body"]


@patch("otto_complete.clients.gitlab.requests.request")
def test_resolve_thread(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    client._last_mr_iid = 10
    result = client.resolve_thread("disc-abc")
    assert result is True

    call_args = mock_request.call_args
    assert call_args[0][0] == "PUT"
    assert "disc-abc" in call_args[0][1]
    assert call_args[1]["json"]["resolved"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: FAIL — methods not found

- [ ] **Step 3: Implement review thread methods**

Add to `GitLabClient` in `otto_complete/clients/gitlab.py`:

```python
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
        try:
            self._put(
                f"/projects/{self.project_path}/merge_requests/{self._last_pr_number}/discussions/{thread_id}",
                json={"resolved": True},
            )
            return True
        except Exception:
            log.warning("Failed to resolve thread %s", thread_id)
            return False
```

Wait — `resolve_thread` takes only `thread_id`, but needs `pr_number` for the API path. The `GitHubClient` uses GraphQL mutation which only needs the thread ID. For GitLab, we need both. Since the protocol only passes `thread_id`, we need to cache the MR number.

Let me fix this: `resolve_thread` will parse the MR number from a composite thread ID format, or we cache it from the last `get_review_threads` call.

Better approach: Use a cached `_last_mr_iid` set during `get_review_threads`. This mirrors how the code always calls `get_review_threads` before `resolve_thread` (see `review.py:110-111` and `review.py:142-149`).

Update the implementation:

```python
    def __init__(self, repo: str, auth=None, base_url: str = "https://gitlab.com"):
        self.repo = repo
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.project_path = quote(repo, safe="")
        self._last_mr_iid: int | None = None
```

In `get_review_threads`, add at the start:
```python
        self._last_mr_iid = pr_number
```

In `reply_to_review_comment`, also set:
```python
        self._last_mr_iid = pr_number
```

In `resolve_thread`:
```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS — all tests

- [ ] **Step 5: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient review thread methods"
```

---

### Task 4: Comment Methods (get_pr_comments, comment_on_pr)

**Files:**
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `tests/test_gitlab.py`

GitLab MR notes = GitHub issue comments. We need to transform the response to match the expected shape.

- [ ] **Step 1: Write tests**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_get_pr_comments(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {
            "id": 501,
            "body": "Looks good!",
            "author": {"username": "reviewer1"},
            "system": False,
        },
        {
            "id": 502,
            "body": "CI passed",
            "author": {"username": "gitlab-bot"},
            "system": True,
        },
    ]
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    comments = client.get_pr_comments(10)

    assert len(comments) == 1  # system notes filtered out
    c = comments[0]
    assert c["id"] == 501
    assert c["body"] == "Looks good!"
    assert c["user"]["login"] == "reviewer1"
    assert c["user"]["type"] == "User"


@patch("otto_complete.clients.gitlab.requests.request")
def test_comment_on_pr(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    result = client.comment_on_pr(10, "Great work!")
    assert result is True

    call_args = mock_request.call_args
    assert call_args[0][0] == "POST"
    body = call_args[1]["json"]["body"]
    assert "Great work!" in body
    assert BOT_MARKER in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: FAIL

- [ ] **Step 3: Implement comment methods**

Add to `GitLabClient` in `otto_complete/clients/gitlab.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient comment methods"
```

---

### Task 5: Reaction Methods (add_reaction, comment_has_reaction)

**Files:**
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `tests/test_gitlab.py`

GitLab uses Award Emoji API. Endpoint: `POST /projects/:id/merge_requests/:iid/notes/:note_id/award_emoji` with `name` parameter. GitHub's `eyes` reaction maps to GitLab's `eyes` emoji name.

Like `resolve_thread`, `add_reaction` and `comment_has_reaction` receive only a `comment_id` but need a `pr_number` for the API path. We'll use `_last_mr_iid` cached from earlier calls.

- [ ] **Step 1: Write tests**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_add_reaction(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    client._last_mr_iid = 10
    result = client.add_reaction(501, "eyes")
    assert result is True

    call_args = mock_request.call_args
    assert call_args[0][0] == "POST"
    assert "/notes/501/award_emoji" in call_args[0][1]
    assert call_args[1]["json"]["name"] == "eyes"


@patch("otto_complete.clients.gitlab.requests.request")
def test_comment_has_reaction_true(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"name": "eyes"}, {"name": "thumbsup"}]
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    client._last_mr_iid = 10
    assert client.comment_has_reaction(501, "eyes") is True


@patch("otto_complete.clients.gitlab.requests.request")
def test_comment_has_reaction_false(mock_request):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"name": "thumbsup"}]
    mock_request.return_value = mock_response

    client = GitLabClient("g/r", auth=PatAuth("token"))
    client._last_mr_iid = 10
    assert client.comment_has_reaction(501, "eyes") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: FAIL

- [ ] **Step 3: Implement reaction methods**

Add to `GitLabClient` in `otto_complete/clients/gitlab.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient reaction methods"
```

---

### Task 6: CI Check Methods (get_pr_checks, get_failed_checks, checks_are_pending, all_checks_pass, format_failed_checks)

**Files:**
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `tests/test_gitlab.py`

GitLab uses Pipelines + Jobs. The flow:
1. `GET /projects/:id/merge_requests/:iid/pipelines` to get pipelines for the MR
2. `GET /projects/:id/pipelines/:pipeline_id/jobs` to get jobs for the latest pipeline
3. Map job statuses to GitHub's `bucket` format: `success` → `pass`, `failed` → `fail`, `pending`/`running`/`created` → `pending`, `skipped`/`manual` → `skipping`

- [ ] **Step 1: Write tests**

Add to `tests/test_gitlab.py`:

```python
@patch("otto_complete.clients.gitlab.requests.request")
def test_get_pr_checks(mock_request):
    # First call: get pipelines for MR
    pipeline_response = MagicMock()
    pipeline_response.raise_for_status = MagicMock()
    pipeline_response.json.return_value = [{"id": 100, "status": "failed"}]

    # Second call: get jobs for pipeline
    jobs_response = MagicMock()
    jobs_response.raise_for_status = MagicMock()
    jobs_response.json.return_value = [
        {
            "name": "unit-tests",
            "status": "failed",
            "stage": "test",
            "web_url": "https://gitlab.com/g/r/-/jobs/201",
            "finished_at": "2026-05-24T10:00:00Z",
        },
        {
            "name": "lint",
            "status": "success",
            "stage": "test",
            "web_url": "https://gitlab.com/g/r/-/jobs/202",
            "finished_at": "2026-05-24T09:55:00Z",
        },
        {
            "name": "deploy",
            "status": "skipped",
            "stage": "deploy",
            "web_url": "https://gitlab.com/g/r/-/jobs/203",
            "finished_at": None,
        },
    ]

    mock_request.side_effect = [pipeline_response, jobs_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    checks = client.get_pr_checks(10)

    assert len(checks) == 3
    assert checks[0]["name"] == "unit-tests"
    assert checks[0]["bucket"] == "fail"
    assert checks[0]["link"] == "https://gitlab.com/g/r/-/jobs/201"
    assert checks[1]["bucket"] == "pass"
    assert checks[2]["bucket"] == "skipping"


@patch("otto_complete.clients.gitlab.requests.request")
def test_get_failed_checks(mock_request):
    pipeline_response = MagicMock()
    pipeline_response.raise_for_status = MagicMock()
    pipeline_response.json.return_value = [{"id": 100}]

    jobs_response = MagicMock()
    jobs_response.raise_for_status = MagicMock()
    jobs_response.json.return_value = [
        {"name": "test", "status": "failed", "stage": "test", "web_url": "", "finished_at": ""},
        {"name": "lint", "status": "success", "stage": "test", "web_url": "", "finished_at": ""},
    ]

    mock_request.side_effect = [pipeline_response, jobs_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    failed = client.get_failed_checks(10)
    assert len(failed) == 1
    assert failed[0]["name"] == "test"


@patch("otto_complete.clients.gitlab.requests.request")
def test_checks_are_pending_running(mock_request):
    pipeline_response = MagicMock()
    pipeline_response.raise_for_status = MagicMock()
    pipeline_response.json.return_value = [{"id": 100}]

    jobs_response = MagicMock()
    jobs_response.raise_for_status = MagicMock()
    jobs_response.json.return_value = [
        {"name": "test", "status": "running", "stage": "test", "web_url": "", "finished_at": None},
    ]

    mock_request.side_effect = [pipeline_response, jobs_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    assert client.checks_are_pending(10) is True


@patch("otto_complete.clients.gitlab.requests.request")
def test_all_checks_pass(mock_request):
    pipeline_response = MagicMock()
    pipeline_response.raise_for_status = MagicMock()
    pipeline_response.json.return_value = [{"id": 100}]

    jobs_response = MagicMock()
    jobs_response.raise_for_status = MagicMock()
    jobs_response.json.return_value = [
        {"name": "test", "status": "success", "stage": "test", "web_url": "", "finished_at": ""},
        {"name": "lint", "status": "success", "stage": "test", "web_url": "", "finished_at": ""},
    ]

    mock_request.side_effect = [pipeline_response, jobs_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    assert client.all_checks_pass(10) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CI check methods**

Add to `GitLabClient` in `otto_complete/clients/gitlab.py`:

```python
    _JOB_STATUS_TO_BUCKET = {
        "success": "pass",
        "failed": "fail",
        "canceled": "fail",
        "pending": "pending",
        "running": "pending",
        "created": "pending",
        "waiting_for_resource": "pending",
        "preparing": "pending",
        "skipped": "skipping",
        "manual": "skipping",
    }

    def get_pr_checks(self, pr_number: int) -> list[dict]:
        try:
            resp = self._get(
                f"/projects/{self.project_path}/merge_requests/{pr_number}/pipelines"
            )
            pipelines = resp.json()
            if not pipelines:
                return []

            latest_pipeline_id = pipelines[0]["id"]
            resp = self._get(
                f"/projects/{self.project_path}/pipelines/{latest_pipeline_id}/jobs",
                params={"per_page": 100},
            )
            jobs = resp.json()
        except Exception:
            log.warning("Failed to fetch CI checks for MR !%d", pr_number)
            return []

        checks = []
        for job in jobs:
            status = job.get("status", "unknown")
            checks.append({
                "name": job.get("name", "unknown"),
                "bucket": self._JOB_STATUS_TO_BUCKET.get(status, "pending"),
                "state": status,
                "description": job.get("stage", ""),
                "link": job.get("web_url", ""),
                "completedAt": job.get("finished_at") or "",
            })
        return checks

    def get_failed_checks(self, pr_number: int) -> list[dict]:
        checks = self.get_pr_checks(pr_number)
        return [c for c in checks if c.get("bucket") == "fail"]

    def checks_are_pending(self, pr_number: int) -> bool:
        checks = self.get_pr_checks(pr_number)
        if not checks:
            return True
        return any(c.get("bucket") == "pending" for c in checks)

    def all_checks_pass(self, pr_number: int) -> bool:
        checks = self.get_pr_checks(pr_number)
        if not checks:
            return False
        return all(c.get("bucket") in ("pass", "skipping") for c in checks)

    def format_failed_checks(self, failed_checks: list[dict]) -> str:
        lines = []
        for c in failed_checks:
            lines.append(f"### Check: {c.get('name', 'unknown')}")
            lines.append(f"- **Status:** {c.get('state', 'unknown')}")
            lines.append(f"- **Description:** {c.get('description') or 'none'}")
            lines.append(f"- **Log URL:** {c.get('link') or 'none'}")
            lines.append("\n---\n")
        return "\n".join(lines) if lines else "No failed check details available."
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gitlab.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add otto_complete/clients/gitlab.py tests/test_gitlab.py
git commit -m "add GitLabClient CI check methods"
```

---

### Task 7: Wire GitLabClient into main.py

**Files:**
- Modify: `otto_complete/main.py`

- [ ] **Step 1: Add GitLabClient import**

In `otto_complete/main.py`, add after the `GitHubClient` import:

```python
from otto_complete.clients.gitlab import GitLabClient
```

- [ ] **Step 2: Update watcher loop to instantiate GitLabClient for gitlab platform**

Replace these lines in the watcher loop:

```python
        target_git = GitClient(config.clone_url, config.clone_path, config.default_branch, auth=auth)
        target_github = GitHubClient(config.repo, auth=auth)
```

With:

```python
        target_git = GitClient(config.clone_url, config.clone_path, config.default_branch, auth=auth)
        if watcher.platform == "gitlab":
            target_github = GitLabClient(config.repo, auth=auth, base_url=watcher.gitlab_url)
        else:
            target_github = GitHubClient(config.repo, auth=auth)
```

And similarly for the workspace repo section, replace:

```python
            ws_git = GitClient(watcher.workspace_clone_url, ws_clone_path, ws_default_branch, auth=auth)
            ws_github = GitHubClient(watcher.workspace_repo, auth=auth)
```

With:

```python
            ws_git = GitClient(watcher.workspace_clone_url, ws_clone_path, ws_default_branch, auth=auth)
            if watcher.platform == "gitlab":
                ws_github = GitLabClient(watcher.workspace_repo, auth=auth, base_url=watcher.gitlab_url)
            else:
                ws_github = GitHubClient(watcher.workspace_repo, auth=auth)
```

- [ ] **Step 3: Verify imports work**

Run: `python -c "from otto_complete.main import main; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add otto_complete/main.py
git commit -m "wire GitLabClient into main loop for gitlab platform watchers"
```

---

### Task 8: Move BOT_MARKER to Shared Location

**Files:**
- Modify: `otto_complete/clients/github.py`
- Modify: `otto_complete/clients/gitlab.py`
- Modify: `otto_complete/review.py`

Currently `BOT_MARKER` is defined in `github.py` and imported by `review.py` and `gitlab.py`. This creates a dependency from `gitlab.py` → `github.py` which is unclean. Move it to `platform.py` which both clients and `review.py` already know about.

- [ ] **Step 1: Add BOT_MARKER to platform.py**

In `otto_complete/clients/platform.py`, add after the imports:

```python
BOT_MARKER = "<!-- otto-complete -->"
```

- [ ] **Step 2: Update github.py to import from platform.py**

In `otto_complete/clients/github.py`, replace:

```python
BOT_MARKER = "<!-- otto-complete -->"
```

With:

```python
from otto_complete.clients.platform import BOT_MARKER
```

- [ ] **Step 3: Update gitlab.py to import from platform.py**

In `otto_complete/clients/gitlab.py`, replace:

```python
from otto_complete.clients.github import BOT_MARKER
```

With:

```python
from otto_complete.clients.platform import BOT_MARKER
```

- [ ] **Step 4: Update review.py to import from platform.py**

In `otto_complete/review.py`, replace:

```python
from otto_complete.clients.github import BOT_MARKER
from otto_complete.clients.platform import CodePlatform
```

With:

```python
from otto_complete.clients.platform import BOT_MARKER, CodePlatform
```

- [ ] **Step 5: Verify all imports work**

Run:

```bash
python -c "
from otto_complete.clients.platform import BOT_MARKER, CodePlatform
from otto_complete.clients.github import GitHubClient, BOT_MARKER
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.review import collect_unaddressed_comments
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add otto_complete/clients/platform.py otto_complete/clients/github.py otto_complete/clients/gitlab.py otto_complete/review.py
git commit -m "move BOT_MARKER to platform.py shared location"
```

---

### Task 9: End-to-End Verification

**Files:** None — verification only

- [ ] **Step 1: Verify all imports**

```bash
python -c "
from otto_complete.clients.auth import AuthProvider, PatAuth
from otto_complete.clients.platform import CodePlatform, BOT_MARKER
from otto_complete.clients.github import GitHubClient
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.config import Config, Watcher, RepoContext
from otto_complete.review import collect_unaddressed_comments
from otto_complete.main import main
print('All imports OK')
"
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (auth tests + config tests + gitlab tests)

- [ ] **Step 3: Verify GitLabClient satisfies CodePlatform structurally**

```bash
python -c "
from otto_complete.clients.platform import CodePlatform
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.clients.auth import PatAuth

client = GitLabClient('g/r', auth=PatAuth('token'))

# Check all protocol methods exist
for method in ['create_pr', 'pr_state', 'pr_is_merged', 'find_pr_by_branch',
               'get_review_threads', 'get_pr_comments', 'reply_to_review_comment',
               'comment_on_pr', 'resolve_thread', 'add_reaction', 'comment_has_reaction',
               'get_pr_checks', 'get_failed_checks', 'checks_are_pending',
               'all_checks_pass', 'format_failed_checks']:
    assert hasattr(client, method), f'Missing method: {method}'

assert hasattr(client, 'repo')
print('GitLabClient satisfies CodePlatform')
"
```

- [ ] **Step 4: Commit if any cleanup needed**

```bash
git add -A
git commit -m "verify GitLabClient end-to-end"
```
