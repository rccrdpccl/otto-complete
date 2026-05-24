from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    @property
    def token(self) -> str: ...


class PatAuth:
    def __init__(self, token: str):
        self._token = token

    @property
    def token(self) -> str:
        return self._token
