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
