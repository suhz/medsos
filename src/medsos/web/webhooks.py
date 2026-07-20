"""Webhooks: handshake, HMAC verify, ingest, dedup, dispatch by the 4 official fields."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

from flask import Blueprint, request, jsonify

from medsos.config import get_settings
from medsos.db import SessionLocal
from medsos.models import Account, Event, Post, Reply
from medsos.platforms.threads.webhook import ThreadsPlatform

bp = Blueprint("webhooks", __name__)
_platform = ThreadsPlatform()


def _account_for_value(value: dict, kind: str):
    with SessionLocal() as s:
        if kind in ("replies", "mentions"):
            owner_id = value.get("root_post", {}).get("owner_id")
            if owner_id is None:
                return None
            return s.query(Account).filter_by(platform_user_id=owner_id).one_or_none()
        if kind == "publish":
            username = value.get("username")
            if username:
                return s.query(Account).filter_by(username=username).one_or_none()
            return None
        if kind == "delete":
            owner_id = value.get("owner", {}).get("owner_id")
            if owner_id is None:
                return None
            return s.query(Account).filter_by(platform_user_id=owner_id).one_or_none()
        return None


@bp.get("/webhooks/<platform>")
def handshake(platform: str):
    s = get_settings()
    if request.args.get("hub.verify_token") != s.webhook_verify_token:
        return ("forbidden", 403)
    return request.args.get("hub.challenge", ""), 200


@bp.post("/webhooks/<platform>")
def ingest(platform: str):
    s = get_settings()
    raw = request.get_data() or b""
    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(s.threads_meta_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return ("bad signature", 401)
    try:
        payload = json.loads(raw.decode())
    except Exception:
        return ("bad json", 400)
    for v in payload.get("values", []):
        _ingest_event(v, payload)
    return jsonify({"ok": True})


def _ingest_event(v: dict, payload: dict) -> None:
    val = v.get("value", {})
    kind = v.get("field", "")
    ev_src = f"{payload.get('app_id')}:{payload.get('time')}:{val.get('id')}:{kind}"
    ev_id = hashlib.sha256(ev_src.encode()).hexdigest()[:32]
    with SessionLocal() as s:
        if s.query(Event).filter_by(platform_event_id=ev_id).first() is not None:
            return
        account = _account_for_value(val, kind)
        s.add(Event(account_id=account.id if account else None,
                    platform_event_id=ev_id, kind=kind, raw=json.dumps(v)))
        s.flush()
        if account is None:
            s.commit()
            return
        if kind in ("replies", "mentions"):
            _ingest_reply(s, account, val, kind)
        elif kind == "publish":
            _ingest_publish(s, account, val)
        elif kind == "delete":
            _ingest_delete(s, account, val)
        s.commit()


def _ingest_reply(s, account, val, kind):
    platform_id = val.get("id")
    if val.get("username") == account.username:
        existing = s.query(Reply).filter_by(account_id=account.id, platform_id=platform_id).one_or_none()
        if existing is None:
            s.add(Reply(
                account_id=account.id, platform_id=platform_id,
                parent_platform_id=val.get("replied_to", {}).get("id") or "",
                root_platform_post_id=val.get("root_post", {}).get("id") or val.get("replied_to", {}).get("id", ""),
                direction="outbound", kind=None, author_username=account.username,
                text=val.get("text", ""), permalink=val.get("permalink"),
                shortcode=val.get("shortcode"), status="published",
                published_at=datetime.utcnow(),
            ))
        else:
            existing.text = val.get("text", existing.text) or existing.text
            existing.permalink = val.get("permalink", existing.permalink) or existing.permalink
            existing.status = "published"
        parent_id = val.get("replied_to", {}).get("id")
        if parent_id:
            p = s.query(Reply).filter_by(account_id=account.id, platform_id=parent_id,
                                        direction="inbound").one_or_none()
            if p is not None and p.status == "new":
                p.status = "replied"
        return
    existing = s.query(Reply).filter_by(account_id=account.id, platform_id=platform_id).one_or_none()
    if existing is not None:
        return
    s.add(Reply(
        account_id=account.id, platform_id=platform_id,
        parent_platform_id=val.get("replied_to", {}).get("id") or "",
        root_platform_post_id=val.get("root_post", {}).get("id") or val.get("replied_to", {}).get("id", ""),
        direction="inbound", kind=kind, author_username=val.get("username"),
        author_id=val.get("author_id"), text=val.get("text", ""),
        permalink=val.get("permalink"), shortcode=val.get("shortcode"),
        status="new",
    ))


def _ingest_publish(s, account, val):
    mid = val.get("id")
    existing = s.query(Post).filter_by(account_id=account.id, platform_media_id=mid).one_or_none()
    if existing is not None:
        existing.status = "published"
        existing.published_at = existing.published_at or datetime.utcnow()
        if val.get("text") and not existing.text:
            existing.text = val.get("text")
        return

    # Prefer adopting an in-flight local publish (status=publishing, no media id
    # yet). Meta's publish webhook often arrives before our publish_post call
    # finishes writing platform_media_id — creating a twin stub causes UNIQUE
    # failures when finalize runs. Attach the media id to the newest inflight row.
    inflight = (
        s.query(Post)
        .filter_by(account_id=account.id, status="publishing")
        .filter(Post.platform_media_id.is_(None))
        .order_by(Post.id.desc())
        .first()
    )
    if inflight is not None:
        inflight.platform_media_id = mid
        inflight.status = "published"
        inflight.published_at = inflight.published_at or datetime.utcnow()
        inflight.error = None
        if val.get("text") and not inflight.text:
            inflight.text = val.get("text")
        return

    s.add(Post(account_id=account.id, platform_media_id=mid,
               text=val.get("text", ""), status="published",
               published_at=datetime.utcnow()))


def _ingest_delete(s, account, val):
    mid = val.get("id")
    p = s.query(Post).filter_by(account_id=account.id, platform_media_id=mid).one_or_none()
    if p is not None:
        p.deleted_at = datetime.utcnow()
    r = s.query(Reply).filter_by(account_id=account.id, platform_id=mid).one_or_none()
    if r is not None:
        r.deleted_at = datetime.utcnow()
