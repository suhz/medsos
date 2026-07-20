"""Threads webhook payload normalizer (the 4 official fields: replies, mentions, publish, delete)."""
from __future__ import annotations

import hashlib
from typing import Any

from medsos.platforms.threads.auth import ThreadsAuth


class ThreadsPlatform:
    name = "threads"

    def authorize_url(self, state: str, scopes: list[str] | None = None) -> str:
        return ThreadsAuth().authorize_url(state, scopes)

    def exchange_code(self, code: str) -> dict[str, Any]:
        return ThreadsAuth().exchange_code(code)

    def parse_account(self, me_payload: dict) -> dict[str, Any]:
        return {"platform_user_id": str(me_payload["id"]), "username": me_payload.get("username", "")}

    def normalize_webhook(self, raw: dict) -> list[dict]:
        out: list[dict] = []
        for v in raw.get("values", []):
            val = v.get("value", {})
            kind = v.get("field", "")
            parent = val.get("replied_to", {}).get("id") or raw.get("target_id")
            root = val.get("root_post", {}).get("id") or parent
            root_owner = val.get("root_post", {}).get("owner_id")
            event_id_src = f"{raw.get('app_id')}:{raw.get('time')}:{val.get('id')}:{kind}"
            event_id = hashlib.sha256(event_id_src.encode()).hexdigest()[:32]
            out.append({
                "event_id": event_id,
                "kind": kind,
                "value": {
                    "platform_id": val.get("id"),
                    "parent_platform_id": parent,
                    "root_platform_post_id": root,
                    "root_owner_id": root_owner,
                    "owner_id": val.get("owner", {}).get("owner_id"),
                    "author_username": val.get("username"),
                    "username": val.get("username"),
                    "text": val.get("text", ""),
                    "media_type": val.get("media_type"),
                    "permalink": val.get("permalink"),
                    "shortcode": val.get("shortcode"),
                    "timestamp": val.get("timestamp"),
                    "deleted_at": val.get("deleted_at"),
                },
            })
        return out
