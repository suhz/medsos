"""Tests for the /accounts OAuth endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch


def test_authorize_returns_url_and_state(client_app):
    rv = client_app.get("/accounts/authorize?platform=threads")
    assert rv.status_code == 200
    data = rv.get_json()
    assert "authorize_url" in data and "state" in data
    assert "client_id=test-app-id" in data["authorize_url"]


def test_callback_upserts_account(client_app, db_url):
    from medsos.db import init_db
    init_db()
    rv = client_app.get("/accounts/authorize?platform=threads")
    state = rv.get_json()["state"]
    with patch("medsos.web.accounts.requests.get") as mock_get, \
         patch("medsos.web.accounts.ThreadsAuth.exchange_code") as mock_ex:
        mock_ex.return_value = {"access_token": "ya29.x",
                                "expires_at": int(datetime.now(timezone.utc).timestamp()) + 3600}
        mock_get.return_value.json.return_value = {"id": "3000000000000001", "username": "test_user"}
        mock_get.return_value.raise_for_status.return_value = None
        rv2 = client_app.get(f"/accounts/callback?code=CODE&state={state}")
    assert rv2.status_code == 200
    from medsos.db import SessionLocal
    from medsos.models import Account
    with SessionLocal() as s:
        a = s.query(Account).one()
    assert a.username == "test_user" and a.platform == "threads"


def test_callback_rejects_bad_state(client_app):
    rv = client_app.get("/accounts/callback?code=CODE&state=NOTREAL")
    assert rv.status_code == 400


def test_callback_surfaces_threads_auth_error(client_app, db_url):
    from medsos.db import init_db
    from medsos.platforms.threads.auth import ThreadsAuthError

    init_db()
    rv = client_app.get("/accounts/authorize?platform=threads")
    state = rv.get_json()["state"]
    err = ThreadsAuthError(
        "token exchange failed: HTTP 400",
        status_code=400,
        body='{"error":"bad redirect"}',
        redirect_uri="https://example.test/accounts/callback",
    )
    with patch("medsos.web.accounts.ThreadsAuth.exchange_code", side_effect=err):
        rv2 = client_app.get(f"/accounts/callback?code=CODE&state={state}")
    assert rv2.status_code == 400
    body = rv2.data.decode()
    assert "token exchange failed: HTTP 400" in body
    assert "redirect_uri=https://example.test/accounts/callback" in body
    assert "bad redirect" in body


def test_get_accounts_lists(client_app, db_url):
    from medsos.db import init_db, SessionLocal
    from medsos.crypto import encrypt_token
    from medsos.models import Account
    from medsos.config import settings
    init_db()
    with SessionLocal() as s:
        s.add(Account(platform="threads", platform_user_id="1", username="u",
                      access_token=encrypt_token(settings.master_key, "x"),
                      token_expires_at=datetime.now(timezone.utc), status="active"))
        s.commit()
    rv = client_app.get("/accounts")
    assert rv.status_code == 200
    data = rv.get_json()
    assert any(a["username"] == "u" for a in data)