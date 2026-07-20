"""medsos-install: discovers HERMES_HOME, wires the plugin symlink.

Console-script entry point defined in pyproject.toml (`medsos-install`).
Cross-platform: POSIX symlinks (Windows junctions not covered in v1).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def compute_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    return Path.home() / ".hermes"


def plan_plugin_link(hermes_home: Path, plugin_src: Path) -> tuple[Path, Path]:
    target = hermes_home / "plugins" / "medsos"
    return target, plugin_src


def create_plugin_link(hermes_home: Path, plugin_src: Path) -> Path:
    target, _ = plan_plugin_link(hermes_home, plugin_src)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        try: target.unlink()
        except IsADirectoryError: pass
    os.symlink(plugin_src, target)
    return target


def remove_plugin_link(hermes_home: Path) -> None:
    target = hermes_home / "plugins" / "medsos"
    if target.is_symlink() or target.exists():
        try: target.unlink()
        except (IsADirectoryError, OSError): pass


def main() -> int:
    hh = compute_hermes_home()
    if not hh.exists():
        print(f"medsos: Hermes home not found at {hh} (set HERMES_HOME or install Hermes)", file=sys.stderr)
        return 1
    plugin_src = Path(__file__).resolve().parent.parent.parent / "plugin"
    if not plugin_src.exists():
        print(f"medsos: plugin source not found at {plugin_src}", file=sys.stderr)
        return 1
    link = create_plugin_link(hh, plugin_src)
    print(f"medsos: linked {link} -> {plugin_src}")
    print(
        "medsos: put MEDSOS_* in the Hermes process env "
        "(e.g. $HERMES_HOME/.env or the active profile .env), then restart Hermes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
