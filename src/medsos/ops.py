"""Operations the plugin tools call. Returns plain dicts (plugin layer JSON-encodes)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from medsos.db import SessionLocal
from medsos.models import Account, Post, Reply
from medsos.onboarding import build_authorize_url_and_persist_state
from medsos.platforms.threads.auth import ThreadsAuth

from medsos.platforms.threads.client import ThreadsClient
from medsos import state as state_helpers


# ----- accounts -------------------------------------------------------------
def find_accounts(account_id: int | None = None) -> list[dict]:
    with SessionLocal() as s:
        q = select(Account)
        if account_id is not None:
            q = q.where(Account.id == account_id)
        return [{"id": a.id, "platform": a.platform, "username": a.username, "status": a.status}
                for a in s.execute(q).scalars().all()]

def add_account(platform: str = "threads") -> dict:
    """Build the OAuth authorize URL + a single-use state. The actual code exchange
    happens in the HTTP /accounts/callback (not in this tool).

    Delegates to the shared onboarding helper so the state row is persisted
    to oauth_states — without that, /accounts/callback would 400 with
    'invalid or expired state'.
    """
    return build_authorize_url_and_persist_state(platform)



# ----- posts ----------------------------------------------------------------
def find_posts(account_id: int, *, post_id: int | None = None,
               platform_media_id: str | None = None, status: str | None = None,
               limit: int = 20) -> list[dict]:
    with SessionLocal() as s:
        q = select(Post).where(Post.account_id == account_id)
        if post_id is not None:
            q = q.where(Post.id == post_id)
        if platform_media_id is not None:
            q = q.where(Post.platform_media_id == platform_media_id)
        if status is not None:
            q = q.where(Post.status == status)
        q = q.order_by(Post.created_at.desc()).limit(limit)
        return [{
            "post_id": p.id, "status": p.status, "text": p.text,
            "media_urls": p.media_urls,
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "platform_media_id": p.platform_media_id,
            "created_at": p.created_at.isoformat(),
            "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None,
        } for p in s.execute(q).scalars().all()]


def create_post(account_id: int, text: str, media_urls: list[str] | None = None) -> dict:
    with SessionLocal() as s:
        p = Post(account_id=account_id, text=text,
                 media_urls=json.dumps(media_urls or []), status="draft")
        s.add(p); s.commit(); s.refresh(p)
        return {"post_id": p.id}


def update_post(account_id: int, post_id: int, text: str | None = None,
                media_urls: list[str] | None = None) -> dict:
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if p is None or p.account_id != account_id:
            return {"error": "post not found"}
        state_helpers.assert_can_update_post(p)
        if text is not None:
            p.text = text
        if media_urls is not None:
            p.media_urls = json.dumps(media_urls)
        s.commit()
        return {"ok": True, "post_id": p.id, "status": p.status}


def _finalize_published_post(
    *,
    account_id: int,
    post_id: int,
    remote_id: str,
    text: str | None = None,
) -> int:
    """Mark our post published, absorbing any webhook twin with the same media id.

    Meta often delivers the `publish` webhook before our HTTP publish call
    returns. That webhook may insert a stub Post(platform_media_id=remote_id).
    Blindly setting platform_media_id on our in-flight row then trips
    uq_posts_account_media. Fold the twin into our row and keep post_id stable.
    """
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if p is None or p.account_id != account_id:
            raise ValueError("post not found during finalize")

        twin = (
            s.query(Post)
            .filter(
                Post.account_id == account_id,
                Post.platform_media_id == remote_id,
                Post.id != post_id,
            )
            .one_or_none()
        )
        if twin is not None:
            # Prefer non-empty fields from either side.
            if (not p.text) and twin.text:
                p.text = twin.text
            elif text and not p.text:
                p.text = text
            if twin.media_urls and (not p.media_urls or p.media_urls == "[]"):
                p.media_urls = twin.media_urls
            s.delete(twin)
            s.flush()

        p.status = "published"
        p.platform_media_id = remote_id
        p.published_at = p.published_at or datetime.now(timezone.utc)
        p.error = None
        if text and not p.text:
            p.text = text
        s.commit()
        return p.id


def publish_post(account_id: int, *, post_id: int | None = None, text: str | None = None,
                 media_urls: list[str] | None = None) -> dict:
    with SessionLocal() as s:
        if post_id is None:
            p = Post(account_id=account_id, text=text or "",
                     media_urls=json.dumps(media_urls or []), status="draft")
            s.add(p); s.commit(); s.refresh(p)
        else:
            p = s.get(Post, post_id)
            if p is None or p.account_id != account_id:
                return {"error": "post not found"}
        if p.status == "published":
            return {"ok": True, "post_id": p.id, "platform_media_id": p.platform_media_id, "permalink": None}
        state_helpers.assert_can_publish_post(p)
        p.status = "publishing"
        s.commit(); s.refresh(p)
        account = s.get(Account, account_id)
        assert account is not None
        local_post_id = p.id
        local_text = p.text
    client = ThreadsClient(account)
    media_type = "IMAGE" if (media_urls and len(media_urls) > 0) else "TEXT"
    image_url = media_urls[0] if media_urls else None
    try:
        remote_id = client.publish(media_type=media_type, text=local_text, image_url=image_url)
    except Exception as e:
        with SessionLocal() as s2:
            p2 = s2.get(Post, local_post_id)
            if p2 is not None:
                p2.status = "failed"; p2.error = str(e); s2.commit()
        return {"error": str(e)}
    permalink = None
    try:
        permalink = client.permalink(remote_id).get("permalink")
    except Exception:
        pass
    final_id = _finalize_published_post(
        account_id=account_id, post_id=local_post_id, remote_id=remote_id, text=local_text,
    )
    return {"ok": True, "post_id": final_id, "platform_media_id": remote_id, "permalink": permalink}


def delete_post(account_id: int, post_id: int) -> dict:
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if p is None or p.account_id != account_id:
            return {"error": "post not found"}
        if not p.platform_media_id:
            p.deleted_at = datetime.now(timezone.utc); s.commit()
            return {"ok": True, "deleted": True}
        account = s.get(Account, account_id)
    client = ThreadsClient(account)
    try:
        client.delete(p.platform_media_id)
    except Exception as e:
        return {"error": str(e)}
    with SessionLocal() as s2:
        p2 = s2.get(Post, post_id)
        p2.deleted_at = datetime.now(timezone.utc); s2.commit()
    return {"ok": True, "deleted": True}


# ----- replies -------------------------------------------------------------
def find_replies(account_id: int, *, reply_id: int | None = None,
                 direction: str | None = None, status: str | None = None,
                 full: bool = False, limit: int = 20) -> list[dict]:
    with SessionLocal() as s:
        q = select(Reply).where(Reply.account_id == account_id)
        if reply_id is not None:
            q = q.where(Reply.id == reply_id)
        if direction is not None:
            q = q.where(Reply.direction == direction)
        if status is not None:
            q = q.where(Reply.status == status)
        q = q.order_by(Reply.created_at.desc()).limit(limit)
        rows = list(s.execute(q).scalars().all())
    out = []
    for r in rows:
        item = {
            "reply_id": r.id, "direction": r.direction, "kind": r.kind,
            "status": r.status, "text": r.text, "author_username": r.author_username,
            "permalink": r.permalink,
            "platform_id": r.platform_id,
            "parent_platform_id": r.parent_platform_id,
            "root_platform_post_id": r.root_platform_post_id,
            "created_at": r.created_at.isoformat(),
            "attempts": r.attempts,
            "skip_reason": r.skip_reason,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
        }
        if full:
            # Re-open a session for the thread walk.
            with SessionLocal() as ts:
                item["thread"] = _build_thread(ts, r)
        out.append(item)
    return out


def _build_thread(s, target: Reply) -> list[dict]:
    """Walk the parent chain from `target` back to the root post; return ordered
    [{kind: 'post', text, ...}, {kind: 'reply', ...}, ...] from root -> target."""
    chain: list[dict] = []
    if target.root_platform_post_id:
        rp = s.query(Post).filter_by(account_id=target.account_id,
                                     platform_media_id=target.root_platform_post_id).one_or_none()
        if rp is not None:
            chain.append({"kind": "post", "text": rp.text,
                          "author_username": None, "created_at": rp.created_at.isoformat()})
        siblings = s.query(Reply).filter_by(account_id=target.account_id,
                                            root_platform_post_id=target.root_platform_post_id)\
                                   .order_by(Reply.created_at.asc()).all()
        for r in siblings:
            chain.append({"kind": "reply", "text": r.text,
                          "author_username": r.author_username,
                          "created_at": r.created_at.isoformat(),
                          "platform_id": r.platform_id})
    return chain


def _upsert_outbound_reply(
    *,
    account_id: int,
    inbound_reply_id: int,
    remote_id: str,
    parent_platform_id: str,
    root_platform_post_id: str,
    author_username: str | None,
    text: str,
    permalink: str | None,
) -> str | None:
    """Insert or merge the outbound reply row; mark inbound replied.

    Returns the best-known permalink (may come from a webhook twin).
    """
    with SessionLocal() as s:
        inbound = s.get(Reply, inbound_reply_id)
        if inbound is not None and inbound.account_id == account_id:
            inbound.status = "replied"
            inbound.error = None

        existing = (
            s.query(Reply)
            .filter_by(account_id=account_id, platform_id=remote_id)
            .one_or_none()
        )
        if existing is not None:
            existing.direction = "outbound"
            existing.status = "published"
            existing.parent_platform_id = parent_platform_id or existing.parent_platform_id
            existing.root_platform_post_id = root_platform_post_id or existing.root_platform_post_id
            existing.author_username = author_username or existing.author_username
            if text:
                existing.text = text
            if permalink:
                existing.permalink = permalink
            existing.published_at = existing.published_at or datetime.now(timezone.utc)
            existing.error = None
            s.commit()
            return existing.permalink or permalink

        s.add(Reply(
            account_id=account_id, platform_id=remote_id,
            parent_platform_id=parent_platform_id,
            root_platform_post_id=root_platform_post_id,
            direction="outbound", kind=None, author_username=author_username,
            text=text, permalink=permalink, status="published",
            published_at=datetime.now(timezone.utc),
        ))
        try:
            s.commit()
        except Exception:
            # Concurrent webhook insert of the same platform_id — retry as merge.
            s.rollback()
            existing = (
                s.query(Reply)
                .filter_by(account_id=account_id, platform_id=remote_id)
                .one_or_none()
            )
            if existing is None:
                raise
            inbound = s.get(Reply, inbound_reply_id)
            if inbound is not None and inbound.account_id == account_id:
                inbound.status = "replied"
                inbound.error = None
            existing.direction = "outbound"
            existing.status = "published"
            existing.parent_platform_id = parent_platform_id or existing.parent_platform_id
            existing.root_platform_post_id = root_platform_post_id or existing.root_platform_post_id
            existing.author_username = author_username or existing.author_username
            if text:
                existing.text = text
            if permalink:
                existing.permalink = permalink
            existing.published_at = existing.published_at or datetime.now(timezone.utc)
            s.commit()
            return existing.permalink or permalink
        return permalink


def publish_reply(account_id: int, reply_id: int, text: str,
                  image_url: str | None = None) -> dict:
    with SessionLocal() as s:
        parent = s.get(Reply, reply_id)
        if parent is None or parent.account_id != account_id:
            return {"error": "reply not found"}
        if parent.status not in ("new", "failed"):
            return {"ok": True, "status": parent.status, "reply_platform_id": None}
        state_helpers.assert_can_publish_reply(parent)
        account = s.get(Account, account_id)
        assert account is not None
        parent_platform_id = parent.platform_id
        root_platform_post_id = parent.root_platform_post_id
        author_username = account.username
    client = ThreadsClient(account)
    media_type = "IMAGE" if image_url else "TEXT"
    try:
        remote_id = client.publish(media_type=media_type, text=text, image_url=image_url,
                                   reply_to_id=parent_platform_id)
    except Exception as e:
        with SessionLocal() as s2:
            p = s2.get(Reply, reply_id)
            if p is not None:
                p.attempts += 1; p.error = str(e); s2.commit()
        return {"error": str(e)}
    permalink = None
    try:
        permalink = client.permalink(remote_id).get("permalink")
    except Exception:
        pass
    permalink = _upsert_outbound_reply(
        account_id=account_id,
        inbound_reply_id=reply_id,
        remote_id=remote_id,
        parent_platform_id=parent_platform_id,
        root_platform_post_id=root_platform_post_id,
        author_username=author_username,
        text=text,
        permalink=permalink,
    )
    # Contract: tool returns outbound status "published"; inbound is marked
    # "replied" inside _upsert_outbound_reply.
    return {"ok": True, "status": "published", "reply_platform_id": remote_id, "permalink": permalink}


def update_reply(account_id: int, reply_id: int, status: str, reason: str | None = None) -> dict:
    if status not in ("skipped", "replied", "failed"):
        return {"error": f"invalid status: {status}"}
    with SessionLocal() as s:
        r = s.get(Reply, reply_id)
        if r is None or r.account_id != account_id:
            return {"error": "reply not found"}
        r.status = status
        if reason is not None:
            r.skip_reason = reason
        s.commit()
    return {"ok": True, "status": status}


def delete_reply(account_id: int, reply_id: int) -> dict:
    with SessionLocal() as s:
        r = s.get(Reply, reply_id)
        if r is None or r.account_id != account_id:
            return {"error": "reply not found"}
        if r.direction == "inbound" and not (r.text and r.platform_id):
            r.deleted_at = datetime.now(timezone.utc); s.commit()
            return {"ok": True, "deleted": True}
        account = s.get(Account, account_id)
        target_id = r.platform_id
    client = ThreadsClient(account)
    try:
        client.delete(target_id)
    except Exception as e:
        return {"error": str(e)}
    with SessionLocal() as s2:
        r2 = s2.get(Reply, reply_id)
        r2.deleted_at = datetime.now(timezone.utc); s2.commit()
    return {"ok": True, "deleted": True}


# ----- insights -------------------------------------------------------------
def get_insights(account_id: int, days: int = 2) -> dict:
    with SessionLocal() as s:
        account = s.get(Account, account_id)
        if account is None:
            return {"error": "account not found"}
    client = ThreadsClient(account)
    return client.user_insights(days=days)
