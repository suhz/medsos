"""Tests for medsos.platforms.threads.client.ThreadsClient."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from medsos.config import settings
from medsos.crypto import encrypt_token
from medsos.db import SessionLocal, init_db
from medsos.models import Account
from medsos.platforms.threads.client import ThreadsAPIError, ThreadsClient


@pytest.fixture
def account(db_url):
    init_db()
    with SessionLocal() as s:
        a = Account(
            platform="threads",
            platform_user_id="3000000000000001",
            username="test_user",
            access_token=encrypt_token(settings.master_key, "ya29.init"),
            token_expires_at=datetime.now(timezone.utc),
            status="active",
        )
        s.add(a); s.commit(); s.refresh(a)
        yield a


def _ok(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    r.status_code = 200
    r.ok = True
    return r


def _err(payload, status_code=401):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    r.status_code = status_code
    r.ok = False
    return r


def test_publish_text_returns_id(account):
    """publish() returns the *published* (2nd-step) media id, not the container."""
    client = ThreadsClient(account)
    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep"):
        sess.post.side_effect = [
            _ok({"id": "container123"}),    # /threads (container create)
            _ok({"id": "published789"}),    # /threads_publish
        ]
        sess.get.return_value = _ok({"id": "published789", "permalink": "https://x.test/p1"})
        result = client.publish(media_type="TEXT", text="hello")
    assert result == "published789"


def test_publish_reply_sets_reply_to_id(account):
    """reply_to_id belongs to the container POST, not the publish POST.

    Inspect the FIRST POST (container creation) for the reply_to_id field.
    The publish POST carries only creation_id (no reply_to_id).
    """
    client = ThreadsClient(account)
    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep"):
        sess.post.side_effect = [
            _ok({"id": "container_r1"}),
            _ok({"id": "published_r1"}),
        ]
        sess.get.return_value = _ok(
            {"id": "published_r1", "permalink": "https://x.test/r1"}
        )
        client.publish(media_type="TEXT", text="hi", reply_to_id="parent1")

    container_post = sess.post.call_args_list[0]
    container_form = container_post.kwargs.get("form") or container_post.kwargs.get("data") or {}
    assert container_form.get("reply_to_id") == "parent1"

    publish_post = sess.post.call_args_list[1]
    publish_form = publish_post.kwargs.get("form") or publish_post.kwargs.get("data") or {}
    # the publish step carries only the creation_id — never reply_to_id
    assert "reply_to_id" not in publish_form
    assert publish_form.get("creation_id") == "container_r1"


def test_publish_two_step_flow_with_sleep(account):
    """Threads mandates a 2-step container→publish flow with a ~30s gap.

    Verifies publish() makes TWO POSTs (the second to /threads_publish with
    creation_id) and that time.sleep(self.publish_wait) runs between them.
    """
    client = ThreadsClient(account)
    container_id = "container_abc"
    published_id = "published_xyz"
    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep") as sleep_mock:
        sess.post.side_effect = [
            _ok({"id": container_id}),
            _ok({"id": published_id}),
        ]
        sess.get.return_value = _ok(
            {"id": published_id, "permalink": "https://x.test/p"}
        )
        result = client.publish(media_type="TEXT", text="hello")

    # (a) exactly two POSTs
    assert sess.post.call_count == 2, (
        f"expected 2 POSTs (container + publish), got {sess.post.call_count}"
    )
    # (b) first to /threads (container), second to /threads_publish with creation_id
    first_post = sess.post.call_args_list[0]
    second_post = sess.post.call_args_list[1]
    assert first_post.args[0].endswith("/threads"), (
        f"first POST should target /threads: {first_post.args[0]}"
    )
    assert "/threads_publish" not in first_post.args[0]
    assert second_post.args[0].endswith("/threads_publish"), (
        f"second POST should target /threads_publish: {second_post.args[0]}"
    )
    second_form = second_post.kwargs.get("form") or second_post.kwargs.get("data") or {}
    assert second_form.get("creation_id") == container_id
    # (c) 30s sleep invoked once, between the two posts
    assert sleep_mock.call_count == 1
    assert sleep_mock.call_args.args[0] == client.publish_wait
    # return value is the *published* (2nd-step) id
    assert result == published_id


def test_publish_publish_step_does_not_retry_on_401(account):
    """A 401 on /threads_publish must NOT trigger refresh-retry: the container
    is already created and retrying with a fresh token would just re-publish
    it. Only the container-creation step refreshes on 401.
    """
    client = ThreadsClient(account)
    bad = _err({"error": {"code": 190, "message": "expired"}}, status_code=401)
    container_id = "container_401"
    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep"):
        sess.post.side_effect = [
            _ok({"id": container_id}),  # container create OK
            bad,                        # /threads_publish 401 → no retry
        ]
        with patch.object(client, "_refresh") as refresh:
            refresh.return_value = None
            with pytest.raises(ThreadsAPIError):
                client.publish(media_type="TEXT", text="x")
        # Refresh was NOT called — the publish step does not retry on 401.
        assert refresh.call_count == 0


def test_401_refresh_retry_uses_new_token(account):
    """Critical: post-refresh retry on container create must use the NEW token
    (not the stale one). Catches the setdefault-vs-direct-assign bug from the
    hermes-plugin-build guide.
    """
    client = ThreadsClient(account)
    new_token = "ya29.refreshed"

    bad = _err({"error": {"code": 190, "message": "expired"}}, status_code=401)
    container_retry = _ok({"id": "container456"})
    publish_ok = _ok({"id": "published456"})
    permalink = _ok({"id": "published456", "permalink": "https://x.test/p2"})

    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep"):
        # 2-step flow needs 3 POSTs: bad container, retry container, publish
        sess.post.side_effect = [bad, container_retry, publish_ok]
        sess.get.return_value = permalink
        with patch.object(client, "_refresh") as refresh, \
             patch.object(client, "_save_token") as save:
            refresh.return_value = None
            # Manually mimic what _refresh does: rotate access_token in place.
            def fake_refresh():
                client.access_token = new_token
            refresh.side_effect = fake_refresh
            client.publish(media_type="TEXT", text="x")
            # The retry container POST is the 2nd call overall.
            second_post = sess.post.call_args_list[1]
            params = second_post.kwargs.get("params", {})
            assert params["access_token"] == new_token


def test_delete_returns_true_on_success(account):
    client = ThreadsClient(account)
    with patch.object(client, "_session") as sess:
        sess.delete.return_value = _ok({"success": True})
        assert client.delete("post_x") is True


def test_user_insights_parses_followers_count(account):
    client = ThreadsClient(account)
    fake = {"data": [{"name": "followers_count", "total_value": {"value": 42}}]}
    with patch.object(client, "_session") as sess:
        sess.get.return_value = _ok(fake)
        result = client.user_insights(days=2)
    assert result == {"followers_count": 42}


def test_publish_surfaces_api_error(account):
    client = ThreadsClient(account)
    with patch.object(client, "_session") as sess, \
         patch("medsos.platforms.threads.client.time.sleep"):
        sess.post.side_effect = [
            _ok({"id": "x"}),  # container
            _ok({"id": "y"}),  # publish
        ]
        sess.get.return_value = MagicMock(
            status_code=500,
            ok=False,
            json=MagicMock(side_effect=ValueError("bad")),
            raise_for_status=MagicMock(side_effect=Exception("500")),
        )
        with pytest.raises(ThreadsAPIError):
            client.publish(media_type="TEXT", text="x")
