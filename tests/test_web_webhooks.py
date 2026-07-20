"""Tests for the Flask webhooks endpoint."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from medsos.db import init_db
from medsos.models import Reply


def _make_account(s, platform_user_id="3000000000000001", username="test_user"):
    from medsos.models import Account
    s.add(Account(platform="threads", platform_user_id=platform_user_id,
                  username=username, access_token="dummy"))
    s.commit()


def test_handshake_returns_challenge_when_token_matches(client_app):
    rv = client_app.get(
        "/webhooks/threads?hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=1234"
    )
    assert rv.status_code == 200 and rv.data == b"1234"


def test_handshake_rejects_bad_token(client_app):
    rv = client_app.get("/webhooks/threads?hub.mode=subscribe&hub.verify_token=WRONG&hub.challenge=1")
    assert rv.status_code == 403


def test_post_rejects_bad_signature(client_app):
    body = json.dumps({"app_id": "1", "values": []}).encode()
    rv = client_app.post("/webhooks/threads", data=body,
                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad"})
    assert rv.status_code == 401


def test_post_ingests_reply_creates_inbound_node(client_app, db_url):
    init_db()
    from medsos.db import SessionLocal
    with SessionLocal() as s:
        _make_account(s)
    body = json.dumps({
        "app_id": "1", "topic": "moderate", "target_id": "ROOTP",
        "time": 1783038286, "subscription_id": "S", "has_uid_field": False,
        "values": [{
            "value": {
                "id": "REPLY1", "username": "other_user", "text": "hi",
                "media_type": "TEXT_POST", "permalink": "u", "replied_to": {"id": "ROOTP"},
                "root_post": {"id": "ROOTP", "owner_id": "3000000000000001", "username": "test_user"},
                "shortcode": "x", "timestamp": "2024-01-01T00:00:00+0000",
            }, "field": "replies",
        }],
    }).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    rv = client_app.post("/webhooks/threads", data=body,
                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    assert rv.status_code == 200
    with SessionLocal() as s:
        rows = s.query(Reply).filter_by(platform_id="REPLY1").all()
    assert len(rows) == 1 and rows[0].status == "new"


def test_post_dedup_by_event_id(client_app, db_url):
    init_db()
    from medsos.db import SessionLocal
    with SessionLocal() as s:
        _make_account(s)
    body = json.dumps({
        "app_id": "1", "topic": "moderate", "target_id": "ROOTP",
        "time": 1, "subscription_id": "S", "has_uid_field": False,
        "values": [{
            "value": {
                "id": "REPLY_DUP", "username": "other_user", "text": "hi",
                "media_type": "TEXT_POST", "permalink": "u",
                "replied_to": {"id": "ROOTP"},
                "root_post": {"id": "ROOTP", "owner_id": "3000000000000001", "username": "test_user"},
                "shortcode": "x", "timestamp": "2024-01-01T00:00:00+0000",
            }, "field": "replies",
        }],
    }).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    h = {"Content-Type": "application/json", "X-Hub-Signature-256": sig}
    client_app.post("/webhooks/threads", data=body, headers=h)
    client_app.post("/webhooks/threads", data=body, headers=h)
    with SessionLocal() as s:
        from medsos.models import Event
        n = s.query(Event).count()
    assert n == 1


def test_publish_webhook_adopts_inflight_publishing_post(client_app, db_url):
    """Regression: publish webhook should attach media id to the local
    status=publishing row instead of inserting an empty twin Post."""
    init_db()
    from medsos.db import SessionLocal
    from medsos.models import Post

    with SessionLocal() as s:
        _make_account(s)
        p = Post(account_id=1, text="local body", status="publishing", media_urls="[]")
        s.add(p); s.commit(); s.refresh(p)
        local_id = p.id

    body = json.dumps({
        "app_id": "1", "topic": "moderate", "target_id": "MID1",
        "time": 42, "subscription_id": "S", "has_uid_field": False,
        "values": [{
            "value": {
                "id": "MID1", "username": "test_user", "text": "",
                "media_type": "TEXT_POST",
                "permalink": "https://threads/p/MID1",
                "timestamp": "2024-01-01T00:00:00+0000",
            }, "field": "publish",
        }],
    }).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    rv = client_app.post(
        "/webhooks/threads", data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert rv.status_code == 200
    with SessionLocal() as s:
        rows = s.query(Post).filter_by(account_id=1).all()
        assert len(rows) == 1
        assert rows[0].id == local_id
        assert rows[0].platform_media_id == "MID1"
        assert rows[0].status == "published"
        assert rows[0].text == "local body"