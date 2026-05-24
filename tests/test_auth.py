from otto_complete.clients.auth import AuthProvider, PatAuth


def test_pat_auth_returns_token():
    auth = PatAuth("ghp_abc123")
    assert auth.token == "ghp_abc123"


def test_pat_auth_returns_same_token_on_multiple_calls():
    auth = PatAuth("glpat-xyz789")
    assert auth.token == "glpat-xyz789"
    assert auth.token == "glpat-xyz789"


def test_pat_auth_satisfies_protocol():
    auth = PatAuth("token")
    assert isinstance(auth, AuthProvider)
