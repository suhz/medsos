"""Tool handlers: always return JSON, never raise out."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

plugin_dir = Path(__file__).resolve().parents[1] / "plugin"
sys.path.insert(0, str(plugin_dir))
import tools  # plugin/tools.py via direct import


@pytest.fixture
def acct(db_url):
    from medsos.db import init_db, SessionLocal
    from medsos.crypto import encrypt_token
    from medsos.models import Account
    from medsos.config import settings
    from datetime import datetime, timezone
    init_db()
    with SessionLocal() as s:
        a = Account(platform="threads", platform_user_id="1", username="u",
                    access_token=encrypt_token(settings.master_key, "x"),
                    token_expires_at=datetime.now(timezone.utc), status="active")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


def test_find_accounts_returns_json_list(db_url):
    rv = tools.medsos_find_accounts({})
    parsed = json.loads(rv)
    assert "accounts" in parsed


def test_publish_reply_returns_json_not_raises(acct):
    rv = tools.medsos_publish_reply({"account_id": acct, "reply_id": 999, "text": "x"})
    parsed = json.loads(rv)
    assert "error" in parsed or parsed.get("ok")


def test_publish_post_handles_missing_account():
    rv = tools.medsos_publish_post({"account_id": 99999, "text": "x"})
    parsed = json.loads(rv)
    assert "error" in parsed