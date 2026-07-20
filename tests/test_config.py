"""Tests for medsos.config.Settings."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from medsos.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("MEDSOS_DB_URL", "sqlite:///./x.db")
    monkeypatch.setenv("MEDSOS_MASTER_KEY", "a" * 32 + "=")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_ID", "app-123")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_SECRET", "secret-abc")
    monkeypatch.setenv("MEDSOS_WEBHOOK_VERIFY_TOKEN", "tok")
    monkeypatch.setenv("MEDSOS_CALLBACK_URL_BASE", "https://x.test")
    s = Settings()
    assert s.db_url == "sqlite:///./x.db"
    assert s.threads_meta_app_id == "app-123"
    assert s.publish_wait == 30  # default


def test_settings_missing_required_raises(monkeypatch):
    monkeypatch.delenv("MEDSOS_DB_URL", raising=False)
    monkeypatch.setenv("MEDSOS_MASTER_KEY", "a" * 32 + "=")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_ID", "a")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_SECRET", "a")
    monkeypatch.setenv("MEDSOS_WEBHOOK_VERIFY_TOKEN", "a")
    monkeypatch.setenv("MEDSOS_CALLBACK_URL_BASE", "https://x.test")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_optional_share_dir(monkeypatch):
    monkeypatch.setenv("MEDSOS_DB_URL", "sqlite:///./x.db")
    monkeypatch.setenv("MEDSOS_MASTER_KEY", "a" * 32 + "=")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_ID", "a")
    monkeypatch.setenv("MEDSOS_THREADS_META_APP_SECRET", "a")
    monkeypatch.setenv("MEDSOS_WEBHOOK_VERIFY_TOKEN", "a")
    monkeypatch.setenv("MEDSOS_CALLBACK_URL_BASE", "https://x.test")
    monkeypatch.setenv("MEDSOS_SHARE_DIR", "/tmp/share")
    monkeypatch.setenv("MEDSOS_SHARE_URL_BASE", "https://x.test/share")
    s = Settings()
    assert s.share_dir == "/tmp/share"
