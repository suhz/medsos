"""Threads Graph API client — loads the access token from a DB Account row
(encrypted). The 401-refresh-retry uses `params['access_token'] = <new>`
(NOT setdefault — a common gotcha).
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from medsos.config import get_settings
from medsos.crypto import decrypt_token, encrypt_token
from medsos.db import SessionLocal
from medsos.models import Account

GRAPH_BASE = "https://graph.threads.net/v1.0"
REFRESH_URL = "https://graph.threads.net/refresh_access_token"
MAX_TEXT_LENGTH = 500


class ThreadsAPIError(Exception):
    def __init__(self, msg: str, status_code: int | None = None, error_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code
        self.error_code = error_code


def is_url(s: str) -> bool:
    return isinstance(s, str) and s.lower().startswith(("http://", "https://"))


def _parse_insights(payload: dict) -> dict[str, Any]:
    """Flatten Threads insights response into {metric_name: value}.

    Threads returns `{"data": [{"name": ..., "total_value": {"value": N}, ...}, ...]}`.
    Some metrics use `total_value.value` (counts), others `values` (time-series);
    we only flatten the scalar ones since this is what callers consume.
    """
    out: dict[str, Any] = {}
    for entry in payload.get("data") or []:
        name = entry.get("name")
        if not name:
            continue
        tv = entry.get("total_value")
        if isinstance(tv, dict) and "value" in tv:
            out[name] = tv["value"]
        elif "values" in entry:
            # time-series — keep the last value as a snapshot
            series = entry["values"] or []
            if series and isinstance(series[-1], dict) and "value" in series[-1]:
                out[name] = series[-1]["value"]
    return out


class ThreadsClient:
    """Minimal Threads Graph API client. Token loaded from the DB account row."""

    def __init__(self, account: Account) -> None:
        self.account = account
        s = get_settings()
        self.access_token = decrypt_token(s.master_key, account.access_token)
        self.user_id = account.platform_user_id
        self.publish_wait = s.publish_wait
        self.share_dir = Path(s.share_dir) if s.share_dir else None
        self.share_base = s.share_url_base
        self._session = requests.Session()

    def _save_token(self, new_token: str, expires_at_epoch: int | None = None) -> None:
        """Persist refreshed token: re-encrypt, update the account row."""
        s = get_settings()
        with SessionLocal() as db:
            a = db.get(Account, self.account.id)
            assert a is not None
            a.access_token = encrypt_token(s.master_key, new_token)
            if expires_at_epoch is not None:
                a.token_expires_at = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc)
            db.commit()

    def _refresh(self) -> None:
        """Token-only refresh (no app secret needed). Rotates self.access_token + persists."""
        resp = requests.get(REFRESH_URL, params={"grant_type": "refresh_token",
                                                "access_token": self.access_token}, timeout=30)
        if not resp.ok:
            raise ThreadsAPIError(f"refresh failed: {resp.status_code}", status_code=resp.status_code)
        j = resp.json()
        new = j["access_token"]
        expires_at = int(time.time()) + int(j.get("expires_in", 60 * 24 * 3600))
        self.access_token = new
        self._save_token(new, expires_at)

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 form: dict | None = None, retry_on_401: bool = True):
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        params = dict(params or {})
        # CRITICAL: direct assign (not setdefault) so the post-refresh retry uses
        # the NEW token, not the stale one.
        params["access_token"] = self.access_token
        verb = method.upper()
        if verb == "GET":
            resp = self._session.get(url, params=params, timeout=30)
        elif verb == "POST":
            resp = self._session.post(url, params=params, data=form, timeout=30)
        elif verb == "DELETE":
            resp = self._session.delete(url, params=params, data=form, timeout=30)
        else:
            resp = self._session.request(method, url, params=params, data=form, timeout=30)
        if resp.status_code == 401 and retry_on_401:
            self._refresh()
            return self._request(method, path, params=params, form=form, retry_on_401=False)
        try:
            data = resp.json()
        except Exception:
            raise ThreadsAPIError(f"non-json response {resp.status_code}: {resp.text[:200]}",
                                  status_code=resp.status_code)
        if not resp.ok:
            err = data.get("error") or {}
            raise ThreadsAPIError(err.get("message", f"HTTP {resp.status_code}"),
                                  status_code=resp.status_code,
                                  error_code=err.get("code"))
        return data

    def _build_publish_form(self, *, media_type: str, text: str | None = None,
                            image_url: str | None = None, reply_to_id: str | None = None,
                            topic_tag: str | None = None, alt_text: str | None = None) -> dict[str, Any]:
        form: dict[str, Any] = {"media_type": media_type}
        if text is not None:
            form["text"] = text
        if image_url is not None:
            form["image_url"] = image_url
        if reply_to_id is not None:
            form["reply_to_id"] = reply_to_id
        if topic_tag is not None:
            form["topic_tag"] = topic_tag
        if alt_text is not None:
            form["alt_text"] = alt_text
        return form

    def _create_container(self, *, media_type: str, text: str | None = None,
                          image_url: str | None = None, reply_to_id: str | None = None,
                          topic_tag: str | None = None, alt_text: str | None = None) -> str:
        """Step 1 of Threads' mandatory 2-step publish: create a media container.

        Returns the container's creation_id (Threads media id pre-publish).
        The 401-refresh-retry inside `_request` lets this step rotate the
        access token if it has expired.
        """
        form = self._build_publish_form(media_type=media_type, text=text, image_url=image_url,
                                        reply_to_id=reply_to_id, topic_tag=topic_tag, alt_text=alt_text)
        return self._request("POST", f"/{self.user_id}/threads", form=form)["id"]

    def _publish(self, creation_id: str) -> str:
        """Step 2: sleep `publish_wait` (~30s), then POST the container's
        creation_id to /threads_publish.

        `retry_on_401=False` — at this point the container is already created
        and retrying with a fresh token would just re-publish the same
        container. Only the container-creation step needs 401-refresh-retry.
        """
        time.sleep(self.publish_wait)
        return self._request("POST", f"/{self.user_id}/threads_publish",
                             form={"creation_id": creation_id},
                             retry_on_401=False)["id"]

    def publish(self, *, media_type: str, text: str | None = None,
                image_url: str | None = None, reply_to_id: str | None = None,
                topic_tag: str | None = None, alt_text: str | None = None) -> str:
        """Publish a post (or reply) using Threads' mandatory 2-step
        container→publish flow with a ~30s gap.

        Container create (POST /threads) → sleep self.publish_wait →
        publish (POST /threads_publish with creation_id). After the publish
        POST succeeds, fetch the permalink so callers can resolve the
        canonical URL. If the permalink fetch fails (transient API hiccup),
        the publish has still succeeded — the error is surfaced for the
        caller to decide whether to retry.
        """
        creation_id = self._create_container(
            media_type=media_type, text=text, image_url=image_url,
            reply_to_id=reply_to_id, topic_tag=topic_tag, alt_text=alt_text,
        )
        post_id = self._publish(creation_id)
        # Fetch permalink (may raise ThreadsAPIError — caller decides).
        self.permalink(post_id)
        return post_id

    def delete(self, post_id: str) -> bool:
        return bool(self._request("DELETE", f"/{post_id}", form={}).get("success"))

    def permalink(self, post_id: str) -> dict:
        return self._request("GET", f"/{post_id}",
                             params={"fields": "id,permalink,shortcode,timestamp,media_type,text"})

    def post_insights(self, post_id: str) -> dict:
        raw = self._request("GET", f"/{post_id}/insights",
                            params={"metric": "likes,replies,reposts,quotes,views,shares"})
        return _parse_insights(raw)

    def user_insights(self, *, days: int = 2) -> dict:
        until = int(datetime.now(timezone.utc).timestamp())
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
        raw = self._request("GET", f"/{self.user_id}/threads_insights",
                            params={"metric": "views,likes,replies,reposts,quotes,followers_count,clicks",
                                    "since": since, "until": until})
        return _parse_insights(raw)

    def upload_public(self, local_path: str) -> str:
        if not (self.share_dir and self.share_base):
            raise ThreadsAPIError("upload_public not configured (set MEDSOS_SHARE_DIR + MEDSOS_SHARE_URL_BASE)")
        src = Path(local_path)
        if not src.is_file():
            raise ThreadsAPIError(f"file not found: {local_path}")
        self.share_dir.mkdir(parents=True, exist_ok=True)
        dest = self.share_dir / src.name
        shutil.copy(src, dest)
        return f"{self.share_base}/{src.name}"