# tests/test_config.py
import os
import tempfile
import yaml

from otto_complete.config import load_config


def _write_config(data: dict) -> str:
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def test_watcher_defaults_to_github_app():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "github_app_id": "123",
        "github_app_installation_id": "456",
        "watchers": [{"project": "PROJ"}],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "github_app"
        assert w.token_env == "GITHUB_TOKEN"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_pat_github():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "github",
            "auth": {"method": "pat", "token_env": "MY_GH_PAT"},
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "pat"
        assert w.token_env == "MY_GH_PAT"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_gitlab_defaults():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "gitlab",
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "gitlab"
        assert w.auth_method == "pat"
        assert w.token_env == "GITLAB_TOKEN"
        assert w.gitlab_url == "https://gitlab.com"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_watcher_gitlab_custom_url():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "watchers": [{
            "project": "PROJ",
            "platform": "gitlab",
            "gitlab_url": "https://gitlab.company.com",
            "auth": {"method": "pat", "token_env": "CORP_GL_TOKEN"},
        }],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "gitlab"
        assert w.auth_method == "pat"
        assert w.token_env == "CORP_GL_TOKEN"
        assert w.gitlab_url == "https://gitlab.company.com"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]


def test_backward_compat_no_platform_no_auth():
    path = _write_config({
        "repo": "org/repo",
        "clone_url": "https://github.com/org/repo.git",
        "github_app_id": "123",
        "github_app_installation_id": "456",
        "watchers": [{"project": "PROJ"}],
    })
    os.environ["OTTO_CONFIG"] = path
    try:
        cfg = load_config()
        w = cfg.watchers[0]
        assert w.platform == "github"
        assert w.auth_method == "github_app"
    finally:
        os.unlink(path)
        del os.environ["OTTO_CONFIG"]
