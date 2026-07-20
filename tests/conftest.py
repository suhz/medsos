"""Shared pytest fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture
def db_url(monkeypatch) -> str:
    """Per-test SQLite file in a temp dir."""
    import tempfile

    from medsos.config import reset_settings

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{tmp}/medsos.db"
        monkeypatch.setenv("MEDSOS_DB_URL", url)
        monkeypatch.setenv("MEDSOS_MASTER_KEY", "ujlLEtjAvDlXSaPyhh8QhAXP35MVqRerznMpvL6VgU8=")
        monkeypatch.setenv("MEDSOS_THREADS_META_APP_ID", "test-app-id")
        monkeypatch.setenv("MEDSOS_THREADS_META_APP_SECRET", "test-app-secret")
        monkeypatch.setenv("MEDSOS_WEBHOOK_VERIFY_TOKEN", "test-verify-token")
        monkeypatch.setenv("MEDSOS_CALLBACK_URL_BASE", "https://example.test")
        reset_settings()
        yield url
        reset_settings()


@pytest.fixture
def client_app(db_url):
    """Flask test client (defined once web/app task creates the app factory)."""
    from medsos.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
