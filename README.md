# medsos

A self-hosted **state engine** for social-media accounts, with a native
[Hermes](https://github.com/suhz/hermes) plugin toolset.

medsos owns the things an AI agent needs to actually run a social-media account
safely: a state database, a webhook receiver, OAuth onboarding, a platform
client, and 12 tools that an agent can call directly. It deliberately owns
**no** scheduler, **no** worker, **no** LLM — *when* and *whether* to process
is your concern (a cron, an agent loop, a backfill). The agent decides what
to say; medsos publishes it.

Threads is the v1 platform. X, Mastodon, and Bluesky are on the roadmap via a
`Platform` protocol (see [Architecture](#architecture)).

```text
   META WEBHOOKS                                       AGENT
        │                                                │
        ▼                                                ▼
 ┌──────────────┐                                  ┌──────────────────┐
 │ /webhooks/   │  handshake + HMAC + ingest       │  medsos_find_…   │
 │   threads    │ ──────────────────────────────▶ │  medsos_publish_…│
 │              │                                  │  medsos_update_… │
 │ /accounts/   │  OAuth authorize + callback      │  medsos_delete_… │
 │   callback   │                                  │  medsos_get_…   │
 └──────┬───────┘                                  └────────┬─────────┘
        │                                                  │
        └──────────────┬───────────────────────┬───────────┘
                       ▼                       ▼
              ┌────────────────────────────────────┐
              │  SQLite or PostgreSQL state DB    │
              │  (posts, replies, accounts,       │
              │   events, oauth_states)           │
              └────────────────────────────────────┘
```

## Who is this for

- **Hermes agent builders** who want their agent to read, draft, post, and
  reply on a social account without writing the platform plumbing.
- **Self-hosters** who want full control over their social-media data, tokens,
  and state — no third-party SaaS in the loop.
- **Multi-platform tool authors** who want to add a new social platform by
  writing a `Platform` adapter, not a new state engine.

## What you get

- A Flask service exposing `/webhooks/{platform}`, `/accounts/authorize`,
  `/accounts/callback`, `/accounts`, and `/healthz`.
- A Hermes plugin (`plugin/`) that registers 12 tools under toolset `medsos`.
- A SQLAlchemy state model (SQLite or PostgreSQL) with Alembic migrations.
- OAuth account onboarding (token stored encrypted at rest via Fernet).
- A ported Threads Graph API client (2-step container→publish flow with the
  mandatory ~30s settle; 401 → token refresh → retry).
- An idempotent webhook ingest with HMAC verification, event-id deduplication,
  and 4-field dispatch (`replies`, `mentions`, `publish`, `delete`).

medsos does **not** include a scheduler, an LLM, or a worker. You bring your
own loop.

## Install

```sh
git clone <medsos> <your-path>        # or: pip install medsos
cd <your-path>
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env && chmod 600 .env
# Edit .env — see Configuration below.

# Run migrations against your DB
alembic upgrade head

# Wire the Hermes plugin (discovers HERMES_HOME; no fixed folder)
medsos-install

# Dev: run the API in the foreground
python scripts/serve.py
```

The service binds `127.0.0.1:8768` by default. For a real install you still need:

1. **`MEDSOS_*` in two places** — the API process and the Hermes process (they do not share env automatically). See [Configuration](#configuration) and [Hermes plugin setup](#hermes-plugin-setup).
2. **An always-on API** — see [Run as a daemon](#run-as-a-daemon).
3. **A public URL** for webhooks + OAuth — see [Reverse proxy](#reverse-proxy).

## Configuration

All env vars are `MEDSOS_`-prefixed. Required:

| Var | Purpose |
|---|---|
| `MEDSOS_DB_URL` | `sqlite:///./medsos.db` or `postgresql+psycopg://user:pass@host/db` |
| `MEDSOS_MASTER_KEY` | Fernet key for token at-rest encryption. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `MEDSOS_THREADS_META_APP_ID` | Threads (Meta) App ID from the Meta developer dashboard |
| `MEDSOS_THREADS_META_APP_SECRET` | Threads (Meta) App Secret |
| `MEDSOS_WEBHOOK_VERIFY_TOKEN` | Webhook handshake token (set the same string in the Meta dashboard) |
| `MEDSOS_CALLBACK_URL_BASE` | Public base URL the OAuth callback + webhook are reachable at (e.g. `https://medsos.example.com`) |

Optional:

| Var | Purpose |
|---|---|
| `MEDSOS_PUBLISH_WAIT` | Seconds between Threads container create and publish (default 30 — required by Threads) |
| `MEDSOS_SHARE_DIR` | Local directory for image hosting (gates `upload_public`) |
| `MEDSOS_SHARE_URL_BASE` | Public URL prefix for `MEDSOS_SHARE_DIR` |

See `.env.example` for a copy-paste template.

### Two processes, two env loads

| Process | Needs `MEDSOS_*`? | Typical source |
|---|---|---|
| Flask API (`scripts/serve.py` / systemd) | yes | project `.env` via `EnvironmentFile=` or your process manager |
| Hermes agent (plugin tools) | yes | `$HERMES_HOME/.env`, or the active profile at `~/.hermes/profiles/<name>/.env` |

Hermes does **not** read the medsos project `.env`. Copy the same keys (or symlink one file into both places). After changing Hermes env, restart Hermes (or use `/reload` where available). After changing the API's env, restart the API/daemon.

Absolute SQLite URLs are less surprising across cwd changes, e.g.
`MEDSOS_DB_URL=sqlite:////var/lib/medsos/medsos.db`.

## Hermes plugin setup

```sh
# From the medsos checkout (sets HERMES_HOME if you use a profile):
export HERMES_HOME="$HOME/.hermes/profiles/<name>"   # optional; default is ~/.hermes
medsos-install
```

Then:

1. **Enable the plugin** in Hermes config (`$HERMES_HOME/config.yaml`):

   ```yaml
   plugins:
     enabled:
       - medsos
   ```

2. **Put `MEDSOS_*` in the Hermes env file** Hermes actually loads:

   - default home: `~/.hermes/.env`
   - named profile: `~/.hermes/profiles/<name>/.env`

   ```sh
   # Example: append from the project .env (review before running)
   grep '^MEDSOS_' .env >> "$HERMES_HOME/.env"
   chmod 600 "$HERMES_HOME/.env"
   ```

3. **Restart Hermes** (CLI session and/or gateway) so the plugin and env load.

4. **Smoke-check** from the agent: call `medsos_find_accounts` (empty list is fine before OAuth).

`medsos-install` only creates the plugin symlink under `$HERMES_HOME/plugins/medsos`. It does not copy secrets and does not enable the plugin in `config.yaml`.

## Run as a daemon

`python scripts/serve.py` is fine for development. For Meta webhooks and OAuth you want something that stays up after logout.

### systemd user unit (recommended)

A template lives at [`deploy/medsos.service.example`](./deploy/medsos.service.example):

```sh
mkdir -p ~/.config/systemd/user
cp deploy/medsos.service.example ~/.config/systemd/user/medsos.service

# Edit REPLACE_MEDSOS_ROOT (and optional EnvironmentFile) to your paths.
# Example EnvironmentFile options:
#   EnvironmentFile=%h/src/medsos/.env
#   EnvironmentFile=%h/.hermes/profiles/mybot/.env

systemctl --user daemon-reload
systemctl --user enable --now medsos.service

# Survive SSH logout:
loginctl enable-linger "$USER"

curl -sS http://127.0.0.1:8768/healthz
# → {"ok":true}

systemctl --user status medsos.service
journalctl --user -u medsos.service -f
```

Notes:

- The example binds via `scripts/serve.py` on loopback only. Put nginx/Caddy (or a tunnel) in front — see [Reverse proxy](#reverse-proxy).
- For heavier traffic, swap `ExecStart` for a real WSGI server, e.g.
  `.../.venv/bin/gunicorn -b 127.0.0.1:8768 'medsos.web.app:create_app()'`.
- `EnvironmentFile=` wants simple `KEY=VALUE` lines (no `export`, limited shell syntax).
- Restart after env edits: `systemctl --user restart medsos.service`.

### Foreground / other supervisors

```sh
set -a && source .env && set +a
python scripts/serve.py
# or: gunicorn -b 127.0.0.1:8768 'medsos.web.app:create_app()'
```

Docker, launchd, or a PaaS work the same way: inject `MEDSOS_*`, run the app, expose 8768 only to your reverse proxy.

## First-run checklist

1. Fill project `.env` and run migrations.
2. Start the API (foreground or systemd); `GET /healthz` returns ok.
3. Point a public HTTPS name at `/webhooks/` and `/accounts/` (and usually `/healthz`).
4. In the Meta developer app: set webhook URL + verify token; add OAuth redirect
   `{MEDSOS_CALLBACK_URL_BASE}/accounts/callback`.
5. `medsos-install`, enable plugin, copy `MEDSOS_*` into Hermes env, restart Hermes.
6. From the agent: `medsos_add_account` → open `authorize_url` → approve →
   `medsos_find_accounts` shows the new row.

## Reverse proxy

The Meta webhook and the OAuth callback must both reach the medsos service.
With `MEDSOS_CALLBACK_URL_BASE=https://medsos.example.com`:

- `POST /webhooks/threads` — Meta's webhook delivery (HMAC-verified)
- `GET /accounts/callback` — Meta's OAuth redirect (after the operator approves)

A minimal nginx snippet:

```nginx
location /webhooks/ { proxy_pass http://127.0.0.1:8768; }
location /accounts/ { proxy_pass http://127.0.0.1:8768; }
location /healthz    { proxy_pass http://127.0.0.1:8768; }
```

The webhook URL you register in the Meta dashboard is
`{MEDSOS_CALLBACK_URL_BASE}/webhooks/threads`. The OAuth redirect URI is
`{MEDSOS_CALLBACK_URL_BASE}/accounts/callback` (set automatically from
`MEDSOS_CALLBACK_URL_BASE`).

## The 12 tools

All tools are account-scoped (`account_id` required) **except** `add_account`
and `find_accounts`. Tools return JSON strings and never raise out
(matching the Hermes plugin contract).

### Accounts

| Tool | Input | Effect | Returns |
|---|---|---|---|
| `medsos_find_accounts` | `account_id?` | Find accounts — one if `account_id`, else all | `{"accounts": [{id, platform, username, status}, ...]}` |
| `medsos_add_account` | `platform?` (default `threads`) | Start OAuth; returns the URL the operator follows | `{"authorize_url": "…", "state": "…"}` |

Example:

```json
// medsos_add_account({})
{"authorize_url": "https://threads.net/oauth/authorize?…&state=…", "state": "abc123"}
```

### Posts

| Tool | Input | Effect | Returns |
|---|---|---|---|
| `medsos_find_posts` | `account_id`, `post_id?`, `platform_media_id?`, `status?`, `limit?` | Find posts (filters: `draft`/`publishing`/`published`/`failed`) | `{"posts": [{post_id, status, text, media_urls, published_at, platform_media_id}, ...]}` |
| `medsos_create_post` | `account_id`, `text`, `media_urls?` | Insert a draft post | `{"post_id": 42}` |
| `medsos_update_post` | `account_id`, `post_id`, `text?`, `media_urls?` | Update a **draft** (draft-only — error if `status != 'draft'`) | `{"ok": true, "post_id": 42, "status": "draft"}` |
| `medsos_publish_post` | `account_id`, `post_id?` or `text`, `media_urls?` | Publish to Threads (~30s, 2-step flow) | `{"ok": true, "post_id": 42, "platform_media_id": "…", "permalink": "…"}` |
| `medsos_delete_post` | `account_id`, `post_id` | Delete on Threads + soft-flag locally | `{"ok": true, "deleted": true}` |

### Replies

| Tool | Input | Effect | Returns |
|---|---|---|---|
| `medsos_find_replies` | `account_id`, `reply_id?`, `direction?`, `status?`, `full?`, `limit?` | Find replies (filters: `inbound`/`outbound` + `status`); `full=true` returns the ordered thread (root post → … → this reply) per row | `{"replies": [{reply_id, direction, kind, status, text, author_username, parent_platform_id, root_platform_post_id, thread?}, ...]}` |
| `medsos_publish_reply` | `account_id`, `reply_id`, `text`, `image?` | Reply to a known inbound reply (~30s) | `{"ok": true, "status": "published", "reply_platform_id": "…", "permalink": "…"}` |
| `medsos_update_reply` | `account_id`, `reply_id`, `status`, `reason?` | Set reply status (`skipped`/`replied`/`failed`) + optional reason | `{"ok": true, "status": "skipped"}` |
| `medsos_delete_reply` | `account_id`, `reply_id` | Delete on Threads + soft-flag locally | `{"ok": true, "deleted": true}` |

The automation loop is `find_replies(status='new', direction='inbound', limit=1, full=true)`
→ process → `publish_reply` / `update_reply(status='skipped')`. The `full=true`
flag returns the whole conversation as a `thread` array so the agent can
draft with full context (including middle replies, not just the immediate
parent).

### Insights

| Tool | Input | Effect | Returns |
|---|---|---|---|
| `medsos_get_insights` | `account_id`, `days?` | Read account-level insights (followers, views, likes, replies, reposts) | `{"followers_count": 42, "views": 100, ...}` |

## Architecture

medsos is one always-on Flask service plus a Hermes plugin.

### Storage

| Table | Holds |
|---|---|
| `accounts` | Connected accounts. `access_token` is encrypted at rest with the Fernet key in `MEDSOS_MASTER_KEY`. |
| `posts` | Our own content (top-level). Status: `draft` → `publishing` → `published` (or `failed`). |
| `replies` | All comments — both inbound (others to us) and outbound (our replies). One table; distinguished by `direction` + `status`. Linked by `parent_platform_id` to the immediate parent (post or reply) and `root_platform_post_id` to the root post. |
| `events` | Webhook events, deduped by `platform_event_id`. |
| `oauth_states` | Single-use CSRF tokens for the OAuth flow, 10-min TTL. |

### Webhook ingest (the 4 official Threads fields)

| Field | Source | Account mapping | Stored as |
|---|---|---|---|
| `replies` | someone replied to media we own | by `root_post.owner_id` | inbound reply node |
| `mentions` | someone mentioned us | by mentioned user | inbound reply node (`kind='mentions'`) |
| `publish` | we published media (post or reply) | by `value.username` | outbound post OR outbound reply node |
| `delete` | our media was deleted | by `value.owner.owner_id` | soft-flag (`deleted_at`) on the matching post/reply |

`replies`/`mentions` never carry our own activity (no self-suppression
needed). Our outbound reaches us via `publish` only. The webhook handler is
idempotent on the `event_id` (sha256 of `app_id:time:value.id:field`).

### Tool layer

```
Hermes agent
     │   tools.py  ←── JSON-always/never-raise handlers (12 of them)
     ▼
medsos.ops   ←── state transitions + DB writes + Threads client calls
     │
     ▼
SQLAlchemy / Threads Graph API
```

The plugin's `tools.py` is a thin layer — it validates input, calls
`medsos.ops.*`, and JSON-encodes the result. The plugin contract
(`def handler(args: dict, **kwargs) -> str`) is satisfied end-to-end
(see `tests/test_plugin_tools.py`).

### Threads publish flow

Threads requires a 2-step publish: POST a container to `/{user_id}/threads`,
wait ~30s, then POST `/{user_id}/threads_publish` with the `creation_id`.
`medsos.platforms.threads.client.ThreadsClient.publish` orchestrates this
and blocks for `MEDSOS_PUBLISH_WAIT` seconds (default 30). Token refresh
on 401 is automatic; the retry uses the *new* token, not the stale one.

## Status

| Stage | Status |
|---|---|
| **Now** | Threads (v1) — 12 tools, OAuth, webhooks, 2-step publish, 401-refresh-retry, encrypted token storage, idempotent ingest. |
| **Next** | X (Twitter) and Mastodon adapters (same `Platform` protocol, same 12 tools). Post-/comment-level insights. Per-world scheduler hooks. |
| **Later** | Bluesky. Optional REST / MCP / CLI adapters over the tool layer. Multi-tenant mode. |

## Tests

```sh
. .venv/bin/activate
pytest -q
```

64 tests, all HTTP mocked. No live API calls.

| Test file | What it covers |
|---|---|
| `test_config.py` | MEDSOS_ env-var loading, required-field validation, defaults |
| `test_crypto.py` | Fernet encrypt/decrypt round-trip, bad-key / bad-ciphertext error paths |
| `test_models.py` | DB table creation, insert/select, unique constraints |
| `test_install.py` | `medsos-install` discovers `HERMES_HOME`, creates/removes the plugin symlink |
| `test_platforms_threads_client.py` | 2-step publish, 401-refresh-retry uses new token, delete, insights parsing |
| `test_platforms_threads_auth.py` | OAuth authorize URL params, callback URL, structured exchange errors |
| `test_platforms_threads_webhook.py` | 4-field dispatch, event-id stability, parse_account |
| `test_ops.py` | All 12 operations, publish webhook race absorption, find_replies(full=true) |
| `test_web_webhooks.py` | HMAC verify, handshake, idempotent ingest, publish adopts inflight post |
| `test_web_accounts.py` | OAuth callback onboard + error surface |
| `test_plugin_tools.py` / `test_plugin_register.py` | Plugin JSON contract + registration |
## License

MIT — see [`LICENSE`](./LICENSE).

Copyright (c) 2026 Suhaimi Amir (suhz).

You're free to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the software, subject to keeping the copyright and
permission notice in all copies. The software is provided "as is", without
warranty of any kind.
## Layout

```
medsos/
├── pyproject.toml              # deps + medsos-install console script
├── .env.example                # MEDSOS_* template
├── alembic.ini
├── README.md                   # you are here
├── deploy/
│   └── medsos.service.example  # systemd user unit template
├── src/medsos/
│   ├── config.py               # pydantic-settings Settings
│   ├── crypto.py               # Fernet encrypt/decrypt
│   ├── db.py                   # SQLAlchemy engine + session factory
│   ├── models.py               # Account, Post, Reply, Event, OauthState
│   ├── state.py                # transition invariants
│   ├── ops.py                  # the 12 operations
│   ├── onboarding.py           # shared authorize-URL + state-persistence helper
│   ├── install.py              # medsos-install (HERMES_HOME discovery)
│   ├── platforms/
│   │   ├── base.py             # Platform protocol
│   │   └── threads/            # Threads implementation
│   │       ├── client.py       # Graph API client (2-step publish, 401-retry)
│   │       ├── auth.py         # OAuth authorize + exchange
│   │       └── webhook.py      # 4-field normalizer
│   └── web/                    # Flask service
│       ├── app.py              # app factory
│       ├── webhooks.py         # /webhooks/{platform}
│       ├── accounts.py         # /accounts/{authorize,callback,list}
│       └── health.py           # /healthz
├── plugin/                     # Hermes plugin
│   ├── plugin.yaml             # toolset `medsos`, 12 provides_tools
│   ├── __init__.py             # register(ctx) — dual import
│   ├── schemas.py              # 12 tool schemas (LLM-facing)
│   └── tools.py                # 12 handlers → medsos.ops
├── migrations/                 # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial_accounts_posts_replies_events.py
│       └── 002_add_oauth_states.py
├── scripts/
│   ├── serve.py                # Flask entrypoint
│   └── account.py              # CLI: list accounts
└── tests/                      # mocked unit/integration tests
```

## Adding a new platform

1. Implement `Platform` (`src/medsos/platforms/base.py`) for the new platform.
2. Reuse the unified-reply model in `models.py` and the state machine in
   `state.py` — they are platform-agnostic.
3. Reuse the webhook `Event` table and idempotency for ingest.
4. The 12 tools don't change. Your agent's code stays the same.

## Contributing

PRs welcome. A few things that will speed up review:

- One task per commit (or a few related ones). TDD where it makes sense
  (a failing test in the same commit as the fix).
- Don't add scope to a task. YAGNI — the design is intentionally narrow.
- All env vars are `MEDSOS_`-prefixed.
- New platform adapters implement `Platform`; the tool layer is unchanged.

For bugs, open an issue with the failing scenario, the expected behavior,
and the actual behavior. A reproduction (even a single `pytest` case) is
worth a hundred words.

## License

Pick whatever you want for your fork — medsos itself is provided as-is.
(The vendored `_forum_ai_*.json` corpus in some forks is MIT; check the
specific files you ship.)
