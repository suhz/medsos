"""Configuration loaded from MEDSOS_* env vars (pydantic-settings)."""
from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDSOS_", case_sensitive=False, extra="ignore")

    # Required
    db_url: str
    master_key: str  # Fernet key (urlsafe-base64 32-byte)
    threads_meta_app_id: str
    threads_meta_app_secret: str
    webhook_verify_token: str
    callback_url_base: str

    # Optional
    share_dir: str | None = None
    share_url_base: str | None = None
    publish_wait: int = 30  # seconds, container→publish gap


_settings: Settings | None = None


def reset_settings() -> None:
    """Drop the cached Settings (tests)."""
    global _settings
    _settings = None


def get_settings() -> Settings:
    """Cached settings instance (loads env on first call)."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


class _LazySettings:
    """Proxy that defers Settings() construction until first attribute access.

    Module import must succeed even when MEDSOS_* env vars are not yet set
    (e.g. during `import medsos.config` inside a test that monkeypatches env
    before constructing Settings). First attribute lookup instantiates the
    real Settings and caches it.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)


# Convenience re-export — lazy so bare `import medsos.config` is safe.
settings = _LazySettings()
