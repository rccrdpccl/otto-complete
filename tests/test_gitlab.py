from unittest.mock import patch, MagicMock
from otto_complete.clients.gitlab import GitLabClient
from otto_complete.clients.auth import PatAuth


def test_gitlab_client_init():
    auth = PatAuth("glpat-test123")
    client = GitLabClient("mygroup/myrepo", auth=auth, base_url="https://gitlab.com")
    assert client.repo == "mygroup/myrepo"
    assert client.project_path == "mygroup%2Fmyrepo"
    assert client.base_url == "https://gitlab.com"


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
    disc_response = MagicMock()
    disc_response.raise_for_status = MagicMock()
    disc_response.json.return_value = [
        {"id": "disc-abc", "notes": [{"id": 1001}]},
        {"id": "disc-def", "notes": [{"id": 1002}]},
    ]

    reply_response = MagicMock()
    reply_response.raise_for_status = MagicMock()
    reply_response.json.return_value = {"id": 2001}

    mock_request.side_effect = [disc_response, reply_response]

    client = GitLabClient("g/r", auth=PatAuth("token"))
    result = client.reply_to_review_comment(10, 1001, "Fixed!")
    assert result is True

    reply_call = mock_request.call_args_list[1]
    assert "disc-abc" in reply_call[0][1]

    from otto_complete.clients.github import BOT_MARKER
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

    from otto_complete.clients.github import BOT_MARKER
    assert BOT_MARKER in body


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
