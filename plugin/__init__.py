"""medsos plugin — registers 12 tools under toolset `medsos`."""
from __future__ import annotations

import logging

try:  # package import (Hermes loads the plugin as a package)
    from . import schemas, tools
except ImportError:  # direct import (pytest/scripts run inside the plugin dir)
    import schemas
    import tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Wire the 12 medsos_* tools."""
    try:
        ctx.register_tool(name="medsos_find_accounts", toolset="medsos",
                          schema=schemas.MEDSOS_FIND_ACCOUNTS, handler=tools.medsos_find_accounts)
        ctx.register_tool(name="medsos_add_account", toolset="medsos",
                          schema=schemas.MEDSOS_ADD_ACCOUNT, handler=tools.medsos_add_account)
        ctx.register_tool(name="medsos_find_posts", toolset="medsos",
                          schema=schemas.MEDSOS_FIND_POSTS, handler=tools.medsos_find_posts)
        ctx.register_tool(name="medsos_create_post", toolset="medsos",
                          schema=schemas.MEDSOS_CREATE_POST, handler=tools.medsos_create_post)
        ctx.register_tool(name="medsos_update_post", toolset="medsos",
                          schema=schemas.MEDSOS_UPDATE_POST, handler=tools.medsos_update_post)
        ctx.register_tool(name="medsos_publish_post", toolset="medsos",
                          schema=schemas.MEDSOS_PUBLISH_POST, handler=tools.medsos_publish_post)
        ctx.register_tool(name="medsos_delete_post", toolset="medsos",
                          schema=schemas.MEDSOS_DELETE_POST, handler=tools.medsos_delete_post)
        ctx.register_tool(name="medsos_find_replies", toolset="medsos",
                          schema=schemas.MEDSOS_FIND_REPLIES, handler=tools.medsos_find_replies)
        ctx.register_tool(name="medsos_publish_reply", toolset="medsos",
                          schema=schemas.MEDSOS_PUBLISH_REPLY, handler=tools.medsos_publish_reply)
        ctx.register_tool(name="medsos_update_reply", toolset="medsos",
                          schema=schemas.MEDSOS_UPDATE_REPLY, handler=tools.medsos_update_reply)
        ctx.register_tool(name="medsos_delete_reply", toolset="medsos",
                          schema=schemas.MEDSOS_DELETE_REPLY, handler=tools.medsos_delete_reply)
        ctx.register_tool(name="medsos_get_insights", toolset="medsos",
                          schema=schemas.MEDSOS_GET_INSIGHTS, handler=tools.medsos_get_insights)
    except Exception:
        logger.exception("medsos plugin failed to register")
        raise