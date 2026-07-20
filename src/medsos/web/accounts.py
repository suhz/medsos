"""OAuth authorize + callback + account listing."""
from __future__ import annotations

from datetime import datetime, timezone

import requests
from flask import Blueprint, jsonify, request

from medsos.config import get_settings
from medsos.crypto import encrypt_token
from medsos.db import SessionLocal, init_db
from medsos.models import Account, OauthState
from medsos.onboarding import build_authorize_url_and_persist_state
from medsos.platforms.threads.auth import ThreadsAuth, ThreadsAuthError

bp = Blueprint("accounts", __name__)


# SQLite drops tz info on round-trip even for DateTime(timezone=True) columns,
# so we store/compare naive UTC datetimes here. The OauthState model default
# uses naive datetime.now() too, so we stay consistent with the schema default.
def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@bp.get("/accounts/authorize")
def authorize():
    # Delegate to the shared helper so HTTP authorize and the
    # medsos_add_account plugin tool produce indistinguishable state rows.
    payload = build_authorize_url_and_persist_state(
        platform=request.args.get("platform", "threads"),
    )
    return jsonify(payload)


@bp.get("/accounts/callback")
def callback():
    init_db()
    code = request.args.get("code")
    state = request.args.get("state")
    if not (code and state):
        return ("missing code or state", 400)
    with SessionLocal() as s:
        rec = s.get(OauthState, state)
        if rec is None or rec.expires_at < _now_naive():
            return ("invalid or expired state", 400)
        platform = rec.platform
        # Keep state until exchange succeeds so a Meta 4xx does not
        # immediately look like "invalid state" on refresh.
    try:
        tok = ThreadsAuth().exchange_code(code)
    except ThreadsAuthError as e:
        return (e.public_message(), 400)
    try:
        me = requests.get(
            "https://graph.threads.net/v1.0/me",
            params={"access_token": tok["access_token"], "fields": "id,username"},
            timeout=30,
        )
        me.raise_for_status()
    except requests.HTTPError as e:
        body = (e.response.text or "")[:500] if e.response is not None else ""
        return (f"profile fetch failed: {e} | {body}", 400)
    mej = me.json()
    platform_user_id = str(mej["id"]); username = mej["username"]
    enc = encrypt_token(get_settings().master_key, tok["access_token"])
    expires_at = datetime.fromtimestamp(tok["expires_at"], tz=timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        rec = s.get(OauthState, state)
        if rec is not None:
            s.delete(rec)
        existing = s.query(Account).filter_by(platform=platform, platform_user_id=platform_user_id).one_or_none()
        if existing is None:
            s.add(Account(platform=platform, platform_user_id=platform_user_id, username=username,
                          access_token=enc,
                          token_expires_at=expires_at,
                          status="active"))
        else:
            existing.username = username
            existing.access_token = enc
            existing.token_expires_at = expires_at
            existing.status = "active"
        s.commit()
    return ("account onboarded", 200)


@bp.get("/accounts")
def list_accounts():
    with SessionLocal() as s:
        rows = s.query(Account).all()
    return jsonify([{"id": a.id, "platform": a.platform, "username": a.username, "status": a.status}
                    for a in rows])
