# medsos

Self-hosted **state engine** for social accounts, with a native
[Hermes Agent](https://hermes-agent.nousresearch.com/docs) plugin.

medsos owns what an agent needs to run a social account safely: a state DB,
webhook receiver, OAuth onboarding, platform client, and **12 tools**. It owns
**no** scheduler, worker, or LLM — *when* and *whether* to act is yours (cron,
agent loop, manual). The agent decides what to say; medsos publishes it.

**v1 platform:** Threads. More platforms plug in via a `Platform` protocol later.

```text
  Meta webhooks / OAuth          Hermes agent (plugin tools)
           │                              │
           ▼                              ▼
    ┌─────────────┐                medsos_find_*
    │ medsos API  │                medsos_publish_*
    │ :8768       │                medsos_update_* …
    └──────┬──────┘                       │
           └────────────┬─────────────────┘
                        ▼
              SQLite or PostgreSQL
         (accounts, posts, replies, events)
```

If an agent is helping you install this, point it at **[AGENTS.md](./AGENTS.md)**.

## Requirements

- Python 3.11+
- [Hermes Agent](https://hermes-agent.nousresearch.com/docs) already installed
- A public HTTPS URL that can reach the medsos API (reverse proxy or tunnel)
- A Meta developer app with Threads API access

### Before you start — Meta credentials (human-supplied)

medsos cannot create these for you. Get them from the
[Meta developer dashboard](https://developers.facebook.com/) (Threads app)
**before** filling `.env` or running OAuth:

| You need | Env var | Who provides it |
|---|---|---|
| App ID | `MEDSOS_THREADS_META_APP_ID` | Human, from Meta app settings |
| App Secret | `MEDSOS_THREADS_META_APP_SECRET` | Human, from Meta app settings |
| Webhook verify token | `MEDSOS_WEBHOOK_VERIFY_TOKEN` | Human picks any random string (or agent generates one); human pastes the **same** value into Meta webhook settings |

Also decide your public base URL (`MEDSOS_CALLBACK_URL_BASE`) up front — Meta
OAuth redirect and webhook URL are derived from it.

Agents helping with install: see [AGENTS.md](./AGENTS.md) — do not invent or
guess App ID / App Secret.

## Quick start

```sh
git clone https://github.com/suhz/medsos.git
cd medsos
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env && chmod 600 .env
# edit .env — see Configuration

alembic upgrade head
```

Then finish these three tracks (order matters for OAuth/webhooks):

1. **API up** — [Run the API](#run-the-api)
2. **Public HTTPS** — [Reverse proxy](#reverse-proxy) + Meta dashboard URLs
3. **Hermes plugin** — [Wire Hermes](#wire-hermes)

Smoke path once all three are ready:

```text
agent: medsos_add_account
you:   open authorize_url, approve in browser
agent: medsos_find_accounts   → shows the connected account
```

## Configuration

All vars are `MEDSOS_`-prefixed. Template: [`.env.example`](./.env.example).

| Var | Required | Purpose |
|---|---|---|
| `MEDSOS_DB_URL` | yes | e.g. `sqlite:////var/lib/medsos/medsos.db` (prefer absolute paths) |
| `MEDSOS_MASTER_KEY` | yes | Fernet key — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `MEDSOS_THREADS_META_APP_ID` | yes | Meta app id |
| `MEDSOS_THREADS_META_APP_SECRET` | yes | Meta app secret |
| `MEDSOS_WEBHOOK_VERIFY_TOKEN` | yes | Any random string; same value in Meta webhook settings |
| `MEDSOS_CALLBACK_URL_BASE` | yes | Public base URL, e.g. `https://medsos.example.com` |
| `MEDSOS_PUBLISH_WAIT` | no | Seconds between Threads container create and publish (default `30`) |
| `MEDSOS_SHARE_DIR` / `MEDSOS_SHARE_URL_BASE` | no | Local dir + public URL prefix for image hosting |

### Two processes, two env loads

| Process | Needs `MEDSOS_*`? | Typical source |
|---|---|---|
| medsos API | yes | project `.env` (`EnvironmentFile=` / process manager) |
| Hermes (plugin tools) | yes | `$HERMES_HOME/.env` or `~/.hermes/profiles/<name>/.env` |

Hermes does **not** read the medsos project `.env`. Copy the same keys (or
symlink one file into both places). Restart each process after env changes.

## Run the API

Dev (foreground):

```sh
set -a && source .env && set +a
python scripts/serve.py
# listens on 127.0.0.1:8768
curl -sS http://127.0.0.1:8768/healthz   # → {"ok":true}
```

Daemon (systemd user unit):

```sh
mkdir -p ~/.config/systemd/user
cp deploy/medsos.service.example ~/.config/systemd/user/medsos.service
# edit REPLACE_MEDSOS_ROOT (and EnvironmentFile if needed)
systemctl --user daemon-reload
systemctl --user enable --now medsos.service
loginctl enable-linger "$USER"   # survive SSH logout
```

Optional: swap `ExecStart` for gunicorn under heavier load.

## Reverse proxy

Meta must reach:

| Path | Use |
|---|---|
| `POST {BASE}/webhooks/threads` | Webhook delivery (HMAC) |
| `GET  {BASE}/accounts/callback` | OAuth redirect |
| `GET  {BASE}/healthz` | Health (optional but handy) |

Minimal nginx:

```nginx
location /webhooks/ { proxy_pass http://127.0.0.1:8768; }
location /accounts/ { proxy_pass http://127.0.0.1:8768; }
location /healthz    { proxy_pass http://127.0.0.1:8768; }
```

In the Meta app:

- Webhook URL = `{MEDSOS_CALLBACK_URL_BASE}/webhooks/threads`
- Verify token = `MEDSOS_WEBHOOK_VERIFY_TOKEN`
- OAuth redirect = `{MEDSOS_CALLBACK_URL_BASE}/accounts/callback`

## Wire Hermes

```sh
# if you use a named profile:
export HERMES_HOME="$HOME/.hermes/profiles/<name>"

medsos-install
```

`medsos-install` only symlinks `plugin/` → `$HERMES_HOME/plugins/medsos`.
It does **not** copy secrets or enable the plugin.

1. Enable in `$HERMES_HOME/config.yaml`:

   ```yaml
   plugins:
     enabled:
       - medsos
   ```

2. Put `MEDSOS_*` in the env file Hermes loads:

   ```sh
   grep '^MEDSOS_' .env >> "$HERMES_HOME/.env"
   chmod 600 "$HERMES_HOME/.env"
   ```

3. Restart Hermes (CLI and/or gateway).

4. From the agent: `medsos_find_accounts` (empty list is fine before OAuth).

## Tools

Account-scoped except `medsos_add_account` / `medsos_find_accounts`.
Handlers return JSON strings and never raise (Hermes plugin contract).

| Tool | What it does |
|---|---|
| `medsos_find_accounts` | List accounts, or one by `account_id` |
| `medsos_add_account` | Start OAuth; returns `authorize_url` for the human |
| `medsos_find_posts` | Filter by id / status / limit |
| `medsos_create_post` | Insert draft |
| `medsos_update_post` | Edit draft only |
| `medsos_publish_post` | Publish draft or inline text (~30s Threads 2-step) |
| `medsos_delete_post` | Delete remote + soft-flag local |
| `medsos_find_replies` | Inbound/outbound; `full=true` returns thread context |
| `medsos_publish_reply` | Reply to inbound `reply_id` (~30s) |
| `medsos_update_reply` | Mark `skipped` / `replied` / `failed` |
| `medsos_delete_reply` | Delete remote + soft-flag local |
| `medsos_get_insights` | Account-level metrics |

Typical reply loop:

```text
medsos_find_replies(account_id, status="new", direction="inbound", limit=1, full=true)
  → draft with thread context
  → medsos_publish_reply(...)  or  medsos_update_reply(..., status="skipped")
```

## How it fits together

- **API process** — Flask on loopback: webhooks, OAuth, health.
- **Hermes process** — plugin tools call `medsos.ops` → same DB + Threads Graph API.
- **Tokens** — encrypted at rest with `MEDSOS_MASTER_KEY`.
- **Webhooks** — HMAC-verified; idempotent on event id; fields: `replies`, `mentions`, `publish`, `delete`.
- **Publish** — Threads requires container → wait ~30s → publish; 401 triggers token refresh and retry with the new token.

medsos does not schedule work. Pair with Hermes cron, a gateway loop, or manual tool calls.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Plugin tools fail on settings / missing env | `MEDSOS_*` only in project `.env`, not Hermes env; restart Hermes after copy |
| `medsos_find_accounts` → `[]` forever | OAuth not finished, or API/DB URL differs between processes |
| OAuth callback `invalid or expired state` | API restarted or different DB than the one that stored `oauth_states` (10‑min TTL) |
| Webhook handshake 403 | Verify token mismatch |
| Webhook POST 401 | App secret mismatch / bad HMAC |
| Publish “hangs” ~30s | Normal — `MEDSOS_PUBLISH_WAIT` |
| Tools work, webhooks don’t | Public URL / proxy not reaching `:8768`, or Meta subscription not set |

## Develop

```sh
. .venv/bin/activate
pytest -q          # mocked; no live API
```

Layout worth knowing: `plugin/` (Hermes), `src/medsos/` (ops + platforms + web),
`deploy/medsos.service.example`, `scripts/serve.py`.

## License

MIT — see [LICENSE](./LICENSE). Copyright (c) 2026 Suhaimi Amir (suhz).
