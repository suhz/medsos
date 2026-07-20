"""Verify plugin.register() registers exactly the 12 medsos_* tools."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock


def test_register_registers_twelve_tools():
    plugin_dir = Path(__file__).resolve().parents[1] / "plugin"
    sys.path.insert(0, str(plugin_dir))
    # Brief's verbatim code does `import medsos_plugin`, but `plugin/` on sys.path
    # imports as `plugin` (not `medsos_plugin`) under FileFinder's package rules.
    # Use spec_from_file_location to bind the __init__.py to the name the brief
    # intends, while preserving the dual-import pattern (which falls through to
    # `import schemas / import tools` since there's no parent package).
    init_py = plugin_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location("medsos_plugin", init_py)
    medsos_plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(medsos_plugin)
    ctx = MagicMock()
    medsos_plugin.register(ctx)
    names = [c.kwargs["name"] for c in ctx.register_tool.call_args_list]
    assert len(names) == 12
    expected = {
        "medsos_find_accounts", "medsos_add_account",
        "medsos_find_posts", "medsos_create_post", "medsos_update_post",
        "medsos_publish_post", "medsos_delete_post",
        "medsos_find_replies", "medsos_publish_reply", "medsos_update_reply",
        "medsos_delete_reply", "medsos_get_insights",
    }
    assert set(names) == expected
    for c in ctx.register_tool.call_args_list:
        assert c.kwargs["toolset"] == "medsos"