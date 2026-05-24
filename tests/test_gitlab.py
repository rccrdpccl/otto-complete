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
