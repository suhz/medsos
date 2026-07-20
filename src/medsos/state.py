"""Explicit state-transition helpers + invariants. No hidden side effects."""
from __future__ import annotations

from medsos.models import Post, Reply


def assert_can_publish_reply(reply: Reply) -> None:
    if reply.direction != "inbound":
        raise ValueError(f"publish_reply requires direction='inbound' (got {reply.direction})")
    if reply.status not in ("new", "failed"):
        raise ValueError(f"publish_reply requires status in new/failed (got {reply.status})")


def assert_can_publish_post(post: Post) -> None:
    if post.status == "published":
        return
    if post.status not in ("draft", "failed"):
        raise ValueError(f"publish_post requires status in draft/failed (got {post.status})")


def assert_can_update_post(post: Post) -> None:
    if post.status != "draft":
        raise ValueError(f"update_post is draft-only (status={post.status})")
