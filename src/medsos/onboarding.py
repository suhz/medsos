"""Shared OAuth onboarding helpers.

Both the HTTP `/accounts/authorize` route and the `medsos_add_account` plugin
tool funnel through `build_authorize_url_and_persist_state(platform)` so the
state row is written exactly once and `/accounts/callback` always finds it.

Spec §6 + §9 require the three onboarding paths (HTTP authorize, HTTP POST
/accounts / CLI, plugin tool) to share one code path. This module is that
shared path for the authorize step.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from medsos.db import SessionLocal, init_db
from medsos.models import OauthState
from medsos.platforms.threads.auth import ThreadsAuth

# Single source of truth for state lifetime. The callback rejects rows whose
# expires_at is in the past, so raising this requires editing only one place.
STATE_TTL = timedelta(minutes=10)


def _now_naive() -> datetime:
    """Naive UTC for SQLite (which drops tz info on round-trip)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_authorize_url_and_persist_state(platform: str = "threads") -> dict:
    """Generate a fresh OAuth state, persist it, and return the authorize URL.

    The caller (HTTP route or plugin tool) returns ``{authorize_url, state}``
    to its user; the user agent then hits the URL and the /accounts/callback
    validates the state against the row we just wrote here.

    Idempotent DB init keeps callers that don't pre-init the schema from
    racing on table creation.
    """
    init_db()
    state = secrets.token_urlsafe(24)
    now = _now_naive()
    with SessionLocal() as s:
        s.add(OauthState(
            state=state,
            platform=platform,
            created_at=now,
            expires_at=now + STATE_TTL,
        ))
        s.commit()
    url = ThreadsAuth().authorize_url(state)
    return {"authorize_url": url, "state": state}