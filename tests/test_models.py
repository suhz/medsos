"""Tests for models + DB init."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from medsos.db import engine, init_db, SessionLocal
from medsos.crypto import encrypt_token
from medsos.config import settings
from medsos.models import Account, Post, Reply


def test_init_db_creates_tables(db_url):
    init_db()
    from sqlalchemy import inspect
    insp = inspect(engine())
    tables = set(insp.get_table_names())
    assert {"accounts", "posts", "replies", "events"} <= tables


def test_account_insert_and_select(db_url):
    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        a = Account(
            platform="threads", platform_user_id="3000000000000001",
            username="test_user", access_token=encrypt_token(settings.master_key, "ya29.x"),
            token_expires_at=now, status="active",
        )
        s.add(a); s.commit()
        got = s.query(Account).one()
        assert got.username == "test_user"
        assert got.platform == "threads"


def test_post_unique_platform_media_id_per_account(db_url):
    init_db()
    with SessionLocal() as s:
        a = Account(platform="threads", platform_user_id="1", username="u",
                    access_token=encrypt_token(settings.master_key, "x"),
                    token_expires_at=datetime.now(timezone.utc), status="active")
        s.add(a); s.commit()
        a_id = a.id
        s.add(Post(account_id=a_id, platform_media_id="M1", text="hi",
                   status="published", published_at=datetime.now(timezone.utc)))
        s.commit()
    with pytest.raises(IntegrityError):
        with SessionLocal() as s2:
            s2.add(Post(account_id=a_id, platform_media_id="M1", text="dup",
                        status="published", published_at=datetime.now(timezone.utc)))
            s2.commit()