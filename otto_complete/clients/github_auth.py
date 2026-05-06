import logging
import threading
import time

import jwt
import requests

log = logging.getLogger(__name__)


class GitHubAppAuth:
    def __init__(self, app_id: str, private_key_path: str, installation_id: str):
        with open(private_key_path) as f:
            self.private_key = f.read()
        self.app_id = app_id
        self.installation_id = installation_id
        self._token = ""
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 600, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def _fetch_installation_token(self):
        j = self._generate_jwt()
        resp = requests.post(
            f"https://api.github.com/app/installations/{self.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {j}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        self._token_expires_at = time.time() + 3300
        log.info("GitHub App installation token refreshed (valid ~55 min)")

    @property
    def token(self) -> str:
        with self._lock:
            if time.time() >= self._token_expires_at:
                self._fetch_installation_token()
            return self._token

    def start_refresh_thread(self):
        def _refresh():
            while True:
                time.sleep(3000)
                try:
                    with self._lock:
                        self._fetch_installation_token()
                except Exception:
                    log.exception("Failed to refresh GitHub App token")

        t = threading.Thread(target=_refresh, daemon=True)
        t.start()
