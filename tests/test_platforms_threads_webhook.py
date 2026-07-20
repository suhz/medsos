"""Tests for Meta Threads webhook payload -> normalized events."""
from __future__ import annotations

from medsos.platforms.threads.webhook import ThreadsPlatform

# Synthetic fixture shaped like a Meta replies webhook (no real account data).
SAMPLE_PAYLOAD = {
    "app_id": "1000000000000001", "topic": "moderate",
    "target_id": "2000000000000001", "time": 1700000000,
    "subscription_id": "1000000000000002", "has_uid_field": False,
    "values": [{
        "value": {
            "id": "2000000000000002", "username": "other_user",
            "text": "Is the recycle topic still open from Monday?",
            "media_type": "TEXT_POST",
            "permalink": "https://www.threads.com/@other_user/post/AbCdEfGhIjK",
            "replied_to": {"id": "2000000000000001"},
            "root_post": {"id": "2000000000000001", "owner_id": "3000000000000001", "username": "test_user"},
            "shortcode": "AbCdEfGhIjK", "timestamp": "2024-01-15T12:00:00+0000",
        }, "field": "replies",
    }],
}


def test_normalize_replies_maps_root_and_parent():
    tp = ThreadsPlatform()
    events = tp.normalize_webhook(SAMPLE_PAYLOAD)
    assert len(events) == 1
    e = events[0]
    assert e["kind"] == "replies"
    assert e["value"]["platform_id"] == "2000000000000002"
    assert e["value"]["parent_platform_id"] == "2000000000000001"
    assert e["value"]["root_platform_post_id"] == "2000000000000001"
    assert e["value"]["author_username"] == "other_user"
    assert e["value"]["root_owner_id"] == "3000000000000001"  # test_user


def test_normalize_publish_own_post():
    tp = ThreadsPlatform()
    p = {
        "app_id": "1", "topic": "interaction", "target_id": "78901", "time": 1,
        "values": [{"value": {
            "id": "8901234", "media_type": "TEXT_POST",
            "permalink": "https://x", "timestamp": "2024-08-07T10:33:16+0000",
            "username": "test_username",
        }, "field": "publish"}],
    }
    events = tp.normalize_webhook(p)
    assert events[0]["kind"] == "publish"
    assert events[0]["value"]["username"] == "test_username"
    assert events[0]["value"]["platform_id"] == "8901234"


def test_normalize_delete():
    tp = ThreadsPlatform()
    p = {
        "app_id": "1", "topic": "moderate", "target_id": "78901", "time": 1,
        "values": [{"value": {
            "id": "8901234",
            "owner": {"owner_id": "78901"},
            "deleted_at": "2024-08-07T10:33:16+0000",
            "timestamp": "2024-08-07T10:33:16+0000",
            "username": "test_username",
        }, "field": "delete"}],
    }
    events = tp.normalize_webhook(p)
    assert events[0]["kind"] == "delete"
    assert events[0]["value"]["owner_id"] == "78901"


def test_event_id_is_stable_for_dedup():
    tp = ThreadsPlatform()
    e1 = tp.normalize_webhook(SAMPLE_PAYLOAD)
    e2 = tp.normalize_webhook(SAMPLE_PAYLOAD)
    assert e1[0]["event_id"] == e2[0]["event_id"]


def test_parse_account_from_me_payload():
    tp = ThreadsPlatform()
    got = tp.parse_account({"id": "3000000000000001", "username": "test_user"})
    assert got == {"platform_user_id": "3000000000000001", "username": "test_user"}
