"""Threads OAuth: authorize URL + exchange code. Token refresh lives in client.py.

Reads MEDSOS_THREADS_META_APP_ID/SECRET and MEDSOS_CALLBACK_URL_BASE from
medsos.config.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import requests

from medsos.config import get_settings

# Threads Graph endpoints (graph.threads.net — NOT graph.facebook.com).
OAUTH_BASE = "https://threads.net/oauth/authorize"
TOKEN_URL = "https://graph.threads.net/oauth/access_token"
LONG_LIVED_TOKEN_URL = "https://graph.threads.net/access_token"

DEFAULT_SCOPES = [
    "threads_basic",
    "threads_content_publish",
    "threads_manage_replies",
    "threads_manage_insights",
]


class ThreadsAuthError(Exception):
    """OAuth/token exchange failure with structured debug context."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        redirect_uri: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.redirect_uri = redirect_uri

    def public_message(self) -> str:
        parts = [str(self)]
        if self.redirect_uri:
            parts.append(f"redirect_uri={self.redirect_uri}")
        if self.body:
            parts.append(self.body)
        return " | ".join(parts)


class ThreadsAuth:
    def __init__(self, *, app_id: str | None = None, app_secret: str | None = None,
                 callback_base: str | None = None) -> None:
        # Lazy settings: only loaded when a kwarg is missing. Lets callers
        # (esp. tests) pass explicit values without monkeypatching MEDSOS_*
        # env vars.
        needs_settings = app_id is None or app_secret is None or callback_base is None
        s = get_settings() if needs_settings else None
        self.app_id = app_id if app_id is not None else s.threads_meta_app_id
        self.app_secret = app_secret if app_secret is not None else s.threads_meta_app_secret
        raw_base = callback_base if callback_base is not None else s.callback_url_base
        self.callback_base = raw_base.rstrip("/")

    def callback_url(self) -> str:
        return f"{self.callback_base}/accounts/callback"

    def authorize_url(self, state: str, scopes: list[str] | None = None) -> str:
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.callback_url(),
            "scope": ",".join(scopes or DEFAULT_SCOPES),
            "response_type": "code",
            "state": state,
        }
        return f"{OAUTH_BASE}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange auth code for a long-lived token. Returns {access_token, expires_at (epoch)}.

        Raises ThreadsAuthError on Meta HTTP failures (structured body + redirect_uri).
        """
        redirect_uri = self.callback_url()
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=30,
        )
        if not resp.ok:
            raise ThreadsAuthError(
                f"token exchange failed: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=(resp.text or "")[:500],
                redirect_uri=redirect_uri,
            )
        j = resp.json()
        access_token = j["access_token"]
        expires_in = int(j.get("expires_in", 3600))

        # Short-lived -> long-lived (Threads: grant_type=th_exchange_token).
        # Soft-fail: keep short-lived token if exchange is unavailable.
        ll = requests.get(
            LONG_LIVED_TOKEN_URL,
            params={
                "grant_type": "th_exchange_token",
                "client_secret": self.app_secret,
                "access_token": access_token,
            },
            timeout=30,
        )
        if ll.ok:
            lj = ll.json()
            access_token = lj["access_token"]
            expires_in = int(lj.get("expires_in", 60 * 24 * 3600))

        return {
            "access_token": access_token,
            "expires_at": int(time.time()) + expires_in,
        }
