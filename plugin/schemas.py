"""12 tool schemas for the medsos plugin."""

def _schema(name, description, properties, required=None):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required or []}}

# Accounts -----------------------------------------------------------------
MEDSOS_FIND_ACCOUNTS = _schema(
    "medsos_find_accounts",
    "Find connected Threads accounts. Pass account_id to fetch one; omit to list all.",
    {"account_id": {"type": "integer", "description": "Optional row id. Omit to list all."}},
)

MEDSOS_ADD_ACCOUNT = _schema(
    "medsos_add_account",
    "Start OAuth onboarding for a new (or re-authorize an existing) account. Returns the Meta authorize URL the operator should follow.",
    {"platform": {"type": "string", "description": "Platform id; default 'threads'."}},
)

# Posts --------------------------------------------------------------------
MEDSOS_FIND_POSTS = _schema(
    "medsos_find_posts",
    "Find posts. Pass post_id or platform_media_id to fetch one; pass status to filter; pass limit to cap.",
    {"account_id": {"type": "integer"}, "post_id": {"type": "integer"},
     "platform_media_id": {"type": "string"},
     "status": {"type": "string", "enum": ["draft", "publishing", "published", "failed"]},
     "limit": {"type": "integer"}},
    required=["account_id"],
)

MEDSOS_CREATE_POST = _schema(
    "medsos_create_post", "Create a draft post.",
    {"account_id": {"type": "integer"}, "text": {"type": "string"},
     "media_urls": {"type": "array", "items": {"type": "string"}}},
    required=["account_id", "text"],
)

MEDSOS_UPDATE_POST = _schema(
    "medsos_update_post",
    "Update a draft post (text and/or media_urls). Error if not draft.",
    {"account_id": {"type": "integer"}, "post_id": {"type": "integer"},
     "text": {"type": "string"}, "media_urls": {"type": "array", "items": {"type": "string"}}},
    required=["account_id", "post_id"],
)

MEDSOS_PUBLISH_POST = _schema(
    "medsos_publish_post",
    "Publish a post to Threads. Pass post_id (of a draft) OR inline text. ~30s latency.",
    {"account_id": {"type": "integer"},
     "post_id": {"type": "integer"}, "text": {"type": "string"},
     "media_urls": {"type": "array", "items": {"type": "string"}}},
    required=["account_id"],
)

MEDSOS_DELETE_POST = _schema(
    "medsos_delete_post", "Permanently delete a Threads post and set deleted_at locally.",
    {"account_id": {"type": "integer"}, "post_id": {"type": "integer"}},
    required=["account_id", "post_id"],
)

# Replies ------------------------------------------------------------------
MEDSOS_FIND_REPLIES = _schema(
    "medsos_find_replies",
    "Find replies (inbound or outbound). Pass reply_id to fetch one. Filter by direction/status. Set full=true to receive the full thread (root post + chain) per row.",
    {"account_id": {"type": "integer"}, "reply_id": {"type": "integer"},
     "direction": {"type": "string", "enum": ["inbound", "outbound"]},
     "status": {"type": "string"},
     "full": {"type": "boolean", "description": "Include the full thread per row."},
     "limit": {"type": "integer"}},
    required=["account_id"],
)

MEDSOS_PUBLISH_REPLY = _schema(
    "medsos_publish_reply",
    "Reply to a known inbound reply (reply_id). ~30s. On success creates an outbound node and marks the inbound replied.",
    {"account_id": {"type": "integer"}, "reply_id": {"type": "integer"},
     "text": {"type": "string"}, "image": {"type": "string"}},
    required=["account_id", "reply_id", "text"],
)

MEDSOS_UPDATE_REPLY = _schema(
    "medsos_update_reply",
    "Generic state write: set reply status (skipped/replied/failed) + skip_reason.",
    {"account_id": {"type": "integer"}, "reply_id": {"type": "integer"},
     "status": {"type": "string", "enum": ["skipped", "replied", "failed"]},
     "reason": {"type": "string"}},
    required=["account_id", "reply_id", "status"],
)

MEDSOS_DELETE_REPLY = _schema(
    "medsos_delete_reply", "Permanently delete a Threads reply and set deleted_at locally.",
    {"account_id": {"type": "integer"}, "reply_id": {"type": "integer"}},
    required=["account_id", "reply_id"],
)

# Insights -----------------------------------------------------------------
MEDSOS_GET_INSIGHTS = _schema(
    "medsos_get_insights",
    "Read account-level insights (followers_count, views, likes, replies, reposts).",
    {"account_id": {"type": "integer"}, "days": {"type": "integer", "default": 2}},
    required=["account_id"],
)