"""Tests for medsos.install (medsos-install script)."""
from __future__ import annotations

from medsos.install import compute_hermes_home, plan_plugin_link, create_plugin_link, remove_plugin_link


def test_compute_hermes_home_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert compute_hermes_home() == tmp_path / ".hermes"


def test_compute_hermes_home_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "my_hermes"))
    assert compute_hermes_home() == tmp_path / "my_hermes"


def test_create_and_remove_link(tmp_path):
    hh = tmp_path / ".hermes"; hh.mkdir()
    src = tmp_path / "plugin"; src.mkdir()
    target, _ = plan_plugin_link(hh, src)
    create_plugin_link(hh, src)
    assert target.is_symlink() and target.resolve() == src.resolve()
    remove_plugin_link(hh)
    assert not target.exists()
