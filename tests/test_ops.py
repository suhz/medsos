"""Tests for medsos.ops — the operations the plugin tools call."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from medsos.db import SessionLocal, init_db
from medsos.crypto import encrypt_token
from medsos.config import settings
from medsos.models import Account, Reply
import medsos.ops as ops


@pytest.fixture
def acct(db_url):
    init_db()
    with SessionLocal() as s:
        a = Account(platform="threads", platform_user_id="3000000000000001",
                    username="test_user",
                    access_token=encrypt_token(settings.master_key, "ya29.test"),
                    token_expires_at=datetime.now(timezone.utc), status="active")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


# ---- find_accounts --------------------------------------------------------
def test_find_accounts_all(acct):
    out = ops.find_accounts()
    assert len(out) == 1 and out[0]["username"] == "test_user"


def test_find_accounts_one(acct):
    out = ops.find_accounts(account_id=acct)
    assert len(out) == 1


def test_find_accounts_missing_returns_empty(acct):
    assert ops.find_accounts(account_id=999) == []


# ---- add_account ----------------------------------------------------------
def test_add_account_threads_returns_authorize_url(db_url):
    out = ops.add_account(platform="threads")
    assert "authorize_url" in out and "state" in out
    assert "client_id=" in out["authorize_url"]


# ---- add_account: state must be persisted so /accounts/callback accepts it ----
def test_add_account_persists_state_and_callback_accepts_it(db_url):
    """Regression: medsos_add_account must persist the OAuth state so the
    /accounts/callback handler can validate it. Before the fix, the tool
    generated a state token and built the authorize URL but never wrote the
    row to oauth_states, so the callback returned 400 'invalid or expired
    state' even though the agent followed the URL with code+state intact."""
    from medsos.models import OauthState
    from medsos.web.app import create_app

    init_db()
    out = ops.add_account(platform="threads")
    state = out["state"]

    # 1. The state must exist in the oauth_states table immediately.
    with SessionLocal() as s:
        rec = s.get(OauthState, state)
    assert rec is not None, "add_account must persist the OAuth state row"
    assert rec.platform == "threads"

    # 2. /accounts/callback must accept the same state and onboard an account.
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with patch("medsos.web.accounts.requests.get") as mock_get, \
         patch("medsos.web.accounts.ThreadsAuth.exchange_code") as mock_ex:
        mock_ex.return_value = {
            "access_token": "ya29.x",
            "expires_at": int(datetime.now(timezone.utc).timestamp()) + 3600,
        }
        mock_get.return_value.json.return_value = {"id": "3000000000000001", "username": "test_user"}
        mock_get.return_value.raise_for_status.return_value = None
        rv = client.get(f"/accounts/callback?code=CODE&state={state}")
    assert rv.status_code == 200, f"callback rejected the tool's state: {rv.data!r}"


# ---- find_posts + create + update + publish + delete --------------------
def test_create_then_find_post(acct):
    pid = ops.create_post(acct, "hello")["post_id"]
    out = ops.find_posts(acct, post_id=pid)
    assert out and out[0]["status"] == "draft"


def test_update_post_only_when_draft(acct):
    pid = ops.create_post(acct, "first")["post_id"]
    ops.update_post(acct, pid, text="second")
    out = ops.find_posts(acct, post_id=pid)
    assert out[0]["text"] == "second"


def test_publish_post_calls_client_and_marks_published(acct):
    pid = ops.create_post(acct, "hi")["post_id"]
    with patch("medsos.ops.ThreadsClient") as CM:
        inst = CM.return_value
        inst.publish.return_value = "remote_id_123"
        inst.permalink.return_value = {"permalink": "https://x.test/p123"}
        out = ops.publish_post(acct, post_id=pid)
    assert out["post_id"] == pid
    assert out["platform_media_id"] == "remote_id_123"
    assert ops.find_posts(acct, post_id=pid)[0]["status"] == "published"


def test_publish_post_absorbs_webhook_twin_with_same_media_id(acct):
    """Regression: Meta publish webhook can insert a stub Post with the remote
    media id before publish_post finalizes. Finalize must merge the twin and
    return ok instead of UNIQUE constraint failure."""
    from medsos.models import Post

    pid = ops.create_post(acct, "race text")["post_id"]

    def _publish_and_race(*_a, **_k):
        # Simulate webhook stub landing while API publish is in flight.
        with SessionLocal() as s:
            s.add(Post(
                account_id=acct,
                platform_media_id="REMOTE_RACE",
                text="",
                status="published",
                published_at=datetime.now(timezone.utc),
            ))
            s.commit()
        return "REMOTE_RACE"

    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.publish.side_effect = _publish_and_race
        CM.return_value.permalink.return_value = {"permalink": "https://x.test/race"}
        out = ops.publish_post(acct, post_id=pid)

    assert out.get("ok") is True
    assert out["post_id"] == pid
    assert out["platform_media_id"] == "REMOTE_RACE"
    rows = ops.find_posts(acct, platform_media_id="REMOTE_RACE")
    assert len(rows) == 1
    assert rows[0]["post_id"] == pid
    assert rows[0]["text"] == "race text"
    assert rows[0]["status"] == "published"


def test_publish_post_already_published_is_noop(acct):
    pid = ops.create_post(acct, "x")["post_id"]
    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.publish.return_value = "remote1"
        CM.return_value.permalink.return_value = {"permalink": "u"}
        ops.publish_post(acct, post_id=pid)
    with patch("medsos.ops.ThreadsClient") as CM:
        out = ops.publish_post(acct, post_id=pid)
    assert out["post_id"] == pid
    CM.return_value.publish.assert_not_called()


def test_delete_post_soft_flag_and_api(acct):
    pid = ops.create_post(acct, "x")["post_id"]
    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.delete.return_value = True
        out = ops.delete_post(acct, pid)
    assert out["deleted"] is True
    assert ops.find_posts(acct, post_id=pid)[0]["deleted_at"] is not None


# ---- find_replies + full flag --------------------------------------------
def _mk_inbound(acct, *, platform_id, parent_id, root_id, status="new", author="alice"):
    with SessionLocal() as s:
        r = Reply(account_id=acct, platform_id=platform_id, parent_platform_id=parent_id,
                  root_platform_post_id=root_id, direction="inbound", kind="replies",
                  author_username=author, text="hi", status=status)
        s.add(r); s.commit(); s.refresh(r); return r.id


def test_find_replies_filters_status(acct):
    _mk_inbound(acct, platform_id="R1", parent_id="P1", root_id="P1", status="new")
    _mk_inbound(acct, platform_id="R2", parent_id="P1", root_id="P1", status="skipped")
    out = ops.find_replies(acct, status="new", direction="inbound")
    assert len(out) == 1 and out[0]["platform_id"] == "R1"


def test_find_replies_full_returns_thread(acct):
    """Insert a root post + a chain of replies; full=True should return the ordered thread."""
    from medsos.models import Post
    with SessionLocal() as s:
        p = Post(account_id=acct, platform_media_id="ROOTP", text="root text",
                 status="published", published_at=datetime.now(timezone.utc))
        s.add(p); s.commit()
    _mk_inbound(acct, platform_id="R1", parent_id="ROOTP", root_id="ROOTP", author="a")
    _mk_inbound(acct, platform_id="R2", parent_id="R1", root_id="ROOTP", author="b")
    out = ops.find_replies(acct, reply_id=2, full=True)
    assert out and out[0]["thread"]
    kinds = [step["kind"] for step in out[0]["thread"]]
    assert kinds == ["post", "reply", "reply"]
    assert out[0]["thread"][0]["text"] == "root text"


# ---- publish_reply / update_reply / delete_reply -------------------------
def test_publish_reply_creates_outbound_and_marks_inbound_replied(acct):
    rid = _mk_inbound(acct, platform_id="PARENT", parent_id="P1", root_id="P1")
    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.publish.return_value = "REPLY_REMOTE"
        CM.return_value.permalink.return_value = {"permalink": "u"}
        out = ops.publish_reply(acct, reply_id=rid, text="ack")
    assert out["status"] == "published"
    found = ops.find_replies(acct, direction="outbound")
    assert len(found) == 1 and found[0]["parent_platform_id"] == "PARENT"
    assert ops.find_replies(acct, reply_id=rid)[0]["status"] == "replied"


def test_publish_reply_merges_when_webhook_already_inserted_outbound(acct):
    """Regression: outbound publish webhook can land before publish_reply
    inserts its row. Must upsert instead of UNIQUE on (account_id, platform_id)."""
    rid = _mk_inbound(acct, platform_id="PARENT2", parent_id="P2", root_id="P2")

    def _publish_and_race(*_a, **_k):
        with SessionLocal() as s:
            s.add(Reply(
                account_id=acct,
                platform_id="OUT_RACE",
                parent_platform_id="PARENT2",
                root_platform_post_id="P2",
                direction="outbound",
                author_username="test_user",
                text="from webhook",
                permalink="https://x.test/from-hook",
                status="published",
                published_at=datetime.now(timezone.utc),
            ))
            s.commit()
        return "OUT_RACE"

    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.publish.side_effect = _publish_and_race
        CM.return_value.permalink.return_value = {"permalink": "https://x.test/from-api"}
        out = ops.publish_reply(acct, reply_id=rid, text="from api")

    assert out.get("ok") is True
    assert out["status"] == "published"
    assert out["reply_platform_id"] == "OUT_RACE"
    outbound = ops.find_replies(acct, direction="outbound")
    assert len(outbound) == 1
    assert outbound[0]["platform_id"] == "OUT_RACE"
    assert outbound[0]["text"] == "from api"  # API text wins on merge
    assert outbound[0]["permalink"] == "https://x.test/from-api"
    assert ops.find_replies(acct, reply_id=rid)[0]["status"] == "replied"


def test_publish_reply_noop_if_not_new(acct):
    rid = _mk_inbound(acct, platform_id="X", parent_id="P", root_id="P", status="replied")
    with patch("medsos.ops.ThreadsClient") as CM:
        out = ops.publish_reply(acct, reply_id=rid, text="x")
    assert out["status"] == "replied"
    CM.return_value.publish.assert_not_called()


def test_publish_reply_failure_bumps_attempts(acct):
    rid = _mk_inbound(acct, platform_id="X", parent_id="P", root_id="P")
    with patch("medsos.ops.ThreadsClient") as CM:
        from medsos.platforms.threads.client import ThreadsAPIError
        CM.return_value.publish.side_effect = ThreadsAPIError("boom", status_code=500)
        out = ops.publish_reply(acct, reply_id=rid, text="x")
    assert "error" in out
    row = ops.find_replies(acct, reply_id=rid)[0]
    assert row["status"] == "new"
    assert row["attempts"] == 1


def test_update_reply_skip(acct):
    rid = _mk_inbound(acct, platform_id="X", parent_id="P", root_id="P")
    out = ops.update_reply(acct, reply_id=rid, status="skipped", reason="spam")
    assert out["status"] == "skipped"
    assert ops.find_replies(acct, reply_id=rid)[0]["skip_reason"] == "spam"


def test_delete_reply_soft_flag(acct):
    rid = _mk_inbound(acct, platform_id="X", parent_id="P", root_id="P")
    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.delete.return_value = True
        out = ops.delete_reply(acct, reply_id=rid)
    assert out["deleted"] is True
    assert ops.find_replies(acct, reply_id=rid)[0]["deleted_at"] is not None


# ---- get_insights ---------------------------------------------------------
def test_get_insights_calls_user_insights(acct):
    with patch("medsos.ops.ThreadsClient") as CM:
        CM.return_value.user_insights.return_value = {"followers_count": 42, "views": 100}
        out = ops.get_insights(acct, days=2)
    assert out["followers_count"] == 42
