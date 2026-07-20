"""12 tool handlers — validate + call medsos.ops + return JSON. Never raise."""
from __future__ import annotations

import json
import logging

import medsos.ops as ops

logger = logging.getLogger(__name__)


def _ok(**kw) -> str:
    return json.dumps(kw)


def _err(msg: str, **extra) -> dict:
    return {"error": msg, **extra}


def _int_or_none(v):
    if v is None or v == "": return None
    try: return int(v)
    except (TypeError, ValueError): return None


def _safe(fn, *args, **kwargs):
    """Run an ops call; return a dict (success payload or {"error": ...}).

    The handlers must never raise out — Hermes expects a JSON string either way.
    The ops layer raises domain errors (IntegrityError, ValueError, etc.) for
    bad inputs (missing FKs, invalid status, etc.); the tool layer translates
    them to {"error": ...} so the agent sees a uniform contract.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning("ops call %s failed: %s", fn.__name__, e)
        return _err(str(e))


def medsos_find_accounts(args, **kwargs) -> str:
    return _ok(accounts=_safe(ops.find_accounts, _int_or_none(args.get("account_id"))))


def medsos_add_account(args, **kwargs) -> str:
    return _ok(**_safe(ops.add_account, args.get("platform", "threads")))


def medsos_find_posts(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id"))
    if aid is None: return json.dumps(_err("account_id required"))
    return _ok(posts=_safe(ops.find_posts, aid,
                           post_id=_int_or_none(args.get("post_id")),
                           platform_media_id=args.get("platform_media_id"),
                           status=args.get("status"),
                           limit=_int_or_none(args.get("limit")) or 20))


def medsos_create_post(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id"))
    if aid is None: return json.dumps(_err("account_id required"))
    return _ok(**_safe(ops.create_post, aid, args.get("text", ""), args.get("media_urls")))


def medsos_update_post(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id")); pid = _int_or_none(args.get("post_id"))
    if aid is None or pid is None: return json.dumps(_err("account_id and post_id required"))
    return _ok(**_safe(ops.update_post, aid, pid,
                       text=args.get("text"), media_urls=args.get("media_urls")))


def medsos_publish_post(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id"))
    if aid is None: return json.dumps(_err("account_id required"))
    return _ok(**_safe(ops.publish_post, aid,
                       post_id=_int_or_none(args.get("post_id")),
                       text=args.get("text"), media_urls=args.get("media_urls")))


def medsos_delete_post(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id")); pid = _int_or_none(args.get("post_id"))
    if aid is None or pid is None: return json.dumps(_err("account_id and post_id required"))
    return _ok(**_safe(ops.delete_post, aid, pid))


def medsos_find_replies(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id"))
    if aid is None: return json.dumps(_err("account_id required"))
    return _ok(replies=_safe(ops.find_replies, aid,
                             reply_id=_int_or_none(args.get("reply_id")),
                             direction=args.get("direction"),
                             status=args.get("status"),
                             full=bool(args.get("full", False)),
                             limit=_int_or_none(args.get("limit")) or 20))


def medsos_publish_reply(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id")); rid = _int_or_none(args.get("reply_id"))
    if aid is None or rid is None: return json.dumps(_err("account_id and reply_id required"))
    return _ok(**_safe(ops.publish_reply, aid, rid, args.get("text", ""), args.get("image")))


def medsos_update_reply(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id")); rid = _int_or_none(args.get("reply_id"))
    if aid is None or rid is None: return json.dumps(_err("account_id and reply_id required"))
    return _ok(**_safe(ops.update_reply, aid, rid, args.get("status", "skipped"), args.get("reason")))


def medsos_delete_reply(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id")); rid = _int_or_none(args.get("reply_id"))
    if aid is None or rid is None: return json.dumps(_err("account_id and reply_id required"))
    return _ok(**_safe(ops.delete_reply, aid, rid))


def medsos_get_insights(args, **kwargs) -> str:
    aid = _int_or_none(args.get("account_id"))
    if aid is None: return json.dumps(_err("account_id required"))
    return _ok(**_safe(ops.get_insights, aid, _int_or_none(args.get("days")) or 2))
