# AGENTS.md — help a human get medsos working

This file is for **AI agents** (including Hermes) assisting an operator.
Humans should start with [README.md](./README.md).

## Your job

Get medsos to a working state:

1. API healthy on loopback
2. Public HTTPS reaches webhooks + OAuth callback
3. Hermes plugin loaded with `MEDSOS_*` in **Hermes** env
4. At least one Threads account connected via OAuth
5. A smoke tool call succeeds (`medsos_find_accounts` or a draft post)

Do **not** invent Meta app credentials. Do **not** commit `.env`, `medsos.db`,
or logs. Do **not** print secrets in full — confirm presence/length only.

## Gate 0 — human must supply Meta credentials first

**Stop and ask the human before writing `.env` or starting the API** unless
these are already present (non-empty) in an existing project/Hermes `.env`:

| Credential | Env var | Source |
|---|---|---|
| Threads / Meta **App ID** | `MEDSOS_THREADS_META_APP_ID` | Human only — Meta developer app |
| Threads / Meta **App Secret** | `MEDSOS_THREADS_META_APP_SECRET` | Human only — Meta developer app |
| **Webhook verify token** | `MEDSOS_WEBHOOK_VERIFY_TOKEN` | Human chooses any secret string, **or** you generate one and show it once; human must enter the same value in Meta → Webhooks |

Also get from the human (or confirm):

- Public base URL → `MEDSOS_CALLBACK_URL_BASE` (HTTPS)
- Active Hermes home/profile (`HERMES_HOME` if not default)

You **may** generate without asking:

- `MEDSOS_MASTER_KEY` (Fernet)
- A random `MEDSOS_WEBHOOK_VERIFY_TOKEN` **if** the human agrees to paste it into Meta

You **must not**:

- Fabricate App ID / App Secret
- Proceed to OAuth (`medsos_add_account`) with empty Meta credentials
- Put real secrets in git, chat logs, or commit messages

If the human does not have a Meta Threads app yet, pause setup and give them
short instructions: create app at developers.facebook.com → add Threads →
copy App ID + App Secret → later set webhook URL/verify token when public HTTPS
exists. Resume at Gate 0 when they paste the values.

## Hard constraints

- Two processes: **medsos API** and **Hermes**. They do not share env unless
  the operator configured that.
- `medsos-install` only creates `$HERMES_HOME/plugins/medsos` symlink.
  It does **not** enable the plugin or copy secrets.
- Hermes loads env from `$HERMES_HOME/.env` (default `~/.hermes`) or
  `~/.hermes/profiles/<name>/.env` when using a profile.
- Set `HERMES_HOME` before `medsos-install` if the operator uses a profile.
- OAuth state lives in the DB with ~10 minute TTL — same `MEDSOS_DB_URL` for
  the API that started authorize and the one that receives callback.
- Threads publish blocks ~30s (`MEDSOS_PUBLISH_WAIT`). That is expected.

## Discovery checklist

Run these (adapt paths) and record facts before changing things:

```sh
# repo + python
pwd
test -f pyproject.toml && test -d plugin
python3 --version

# hermes home
echo "HERMES_HOME=${HERMES_HOME:-}"
ls -la "${HERMES_HOME:-$HOME/.hermes}" 2>/dev/null | head
ls -la "$HOME/.hermes/profiles" 2>/dev/null

# existing medsos bits
test -f .env && echo "project .env exists" || echo "no project .env"
test -d .venv && echo "venv exists"
curl -sS -m 2 http://127.0.0.1:8768/healthz || echo "API not up"
systemctl --user is-active medsos.service 2>/dev/null || true

# plugin wired?
ls -la "${HERMES_HOME:-$HOME/.hermes}/plugins/medsos" 2>/dev/null
```

Ask the human only for what you cannot discover (see **Gate 0**):

- Meta App ID / App Secret (required; never invent)
- Webhook verify token (or offer to generate + they paste into Meta)
- Public base URL (`MEDSOS_CALLBACK_URL_BASE`)
- Which Hermes home/profile is active
- systemd vs foreground; existing reverse proxy/tunnel

If Gate 0 values are missing, **do not start the playbook** — collect them first.

## Setup playbook (execute in order)

### A. Install package

```sh
cd <medsos-checkout>
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

### B. Configure `.env`

**Prerequisite:** Gate 0 values in hand (App ID, App Secret, verify token, public base URL).

```sh
cp -n .env.example .env
chmod 600 .env
```

Write required keys (see README Configuration). Use the human’s Meta App ID and
App Secret verbatim. Generate master key if empty:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Prefer an **absolute** SQLite URL if cwd will vary, e.g.
`sqlite:////home/<user>/medsos/medsos.db`.

Sanity-check without dumping secrets:

```sh
grep -E '^MEDSOS_(THREADS_META_APP_ID|THREADS_META_APP_SECRET|WEBHOOK_VERIFY_TOKEN|CALLBACK_URL_BASE|MASTER_KEY)=' .env \
  | sed -E 's/(SECRET|TOKEN|KEY)=.*/\1=<set>/'
```

All five lines should show non-empty / `<set>`. Then:

```sh
alembic upgrade head
```

### C. Start API

Dev:

```sh
set -a && source .env && set +a
python scripts/serve.py   # 127.0.0.1:8768
```

Or systemd user unit from `deploy/medsos.service.example` (replace
`REPLACE_MEDSOS_ROOT`, enable linger).

Verify:

```sh
curl -sS http://127.0.0.1:8768/healthz
# expect {"ok":true}
```

### D. Public URL

Ensure externally:

- `POST {BASE}/webhooks/threads`
- `GET  {BASE}/accounts/callback`

reach `127.0.0.1:8768`. Configure Meta dashboard to match
`MEDSOS_CALLBACK_URL_BASE` + verify token. You cannot complete Meta UI steps
for the human — give them the exact URLs and wait.

### E. Wire Hermes

```sh
export HERMES_HOME=...          # if profile
. .venv/bin/activate
medsos-install
```

Enable plugin in `$HERMES_HOME/config.yaml`:

```yaml
plugins:
  enabled:
    - medsos
```

Copy env into Hermes (review with human first):

```sh
grep '^MEDSOS_' .env >> "$HERMES_HOME/.env"
chmod 600 "$HERMES_HOME/.env"
```

Tell the human to **restart Hermes** (CLI session and/or gateway).

### F. OAuth onboard

1. Call tool `medsos_add_account` (platform default `threads`).
2. Give the human `authorize_url`. They must open it and approve.
3. Callback hits the API → account row written.
4. Call `medsos_find_accounts` — expect `status: active` and a username.

If callback fails, check API logs, `MEDSOS_CALLBACK_URL_BASE`, redirect URI in
Meta app, and that state was created in the **same** DB within 10 minutes.

### G. Smoke

- `medsos_find_accounts`
- Optional: `medsos_create_post` + `medsos_publish_post` (warn: ~30s, public post)
- Optional: after a real reply webhook, `medsos_find_replies` with
  `status=new`, `direction=inbound`, `full=true`

## Done criteria

- [ ] `GET /healthz` → ok
- [ ] Plugin symlink exists under `$HERMES_HOME/plugins/medsos`
- [ ] `medsos` listed under `plugins.enabled` in Hermes config
- [ ] Same critical `MEDSOS_*` present in API env and Hermes env
- [ ] `medsos_find_accounts` returns ≥1 active account
- [ ] (Optional) inbound webhook created a `replies` row after a test reply

## Common failures → fix

| Observation | Fix |
|---|---|
| `Settings` / missing `MEDSOS_*` in tool call | Copy keys into Hermes `.env`; restart Hermes |
| `medsos-install`: Hermes home not found | Install Hermes or export correct `HERMES_HOME` |
| Empty accounts after “successful” OAuth | Callback hit wrong host/DB; compare API `MEDSOS_DB_URL` vs where you looked |
| `invalid or expired state` | Re-run `medsos_add_account`; complete browser flow within TTL; one API instance |
| Webhook 403 on GET handshake | Align verify token Meta ↔ `MEDSOS_WEBHOOK_VERIFY_TOKEN` |
| Webhook 401 on POST | Align app secret; proxy must not alter body (HMAC) |
| Publish errors / double posts | Don’t retry blindly; check `medsos_find_posts` status first |
| Tools see old code | Editable install + Hermes restart; confirm symlink target is this checkout |

## What you should not do

- Put real tokens, app secrets, or production DB contents into git
- Force-push or rewrite history unless the human explicitly asks
- Register Meta webhooks with a non-HTTPS or unreachable URL
- Assume project `.env` is visible to Hermes
- Spam `medsos_publish_*` while debugging

## After setup (optional automation)

medsos will not poll for you. Suggest one of:

- Hermes cron: periodically `medsos_find_replies(status=new, direction=inbound, full=true)` then reply or skip
- Manual: human asks agent to “check Threads inbox”
- Gateway session left running with a standing instruction

Keep the human in control of send/skip policy unless they asked for full auto.

## Reference

- Operator docs: [README.md](./README.md)
- Env template: [.env.example](./.env.example)
- systemd template: [deploy/medsos.service.example](./deploy/medsos.service.example)
- Tool schemas: [plugin/schemas.py](./plugin/schemas.py)
- Hermes docs: https://hermes-agent.nousresearch.com/docs
