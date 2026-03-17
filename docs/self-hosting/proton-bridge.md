# Proton Mail Bridge Setup

Connect a single Proton Mail account to OpenMates so the **mail search skill** can read your inbox.

This is a **single-account, admin-only feature** — one Proton account per deployment, accessible only to the one OpenMates user you designate. It is not a multi-tenant per-user connector.

---

## Prerequisites

- A running **Proton Mail Bridge** instance reachable from your OpenMates server.
  Download: <https://proton.me/mail/bridge>
- A **Proton Mail paid plan** (Bridge requires Proton Mail Plus or above).
- The OpenMates user account whose email address will be granted access.

---

## Setup Steps

### 1. Start Proton Mail Bridge

Launch Bridge and log in with your Proton account. Once connected, Bridge exposes a local IMAP server. Find the credentials in Bridge → **Settings** → **IMAP/SMTP**:

| Value         | Where to find it                                                   |
| ------------- | ------------------------------------------------------------------ |
| IMAP host     | Usually `127.0.0.1`                                                |
| IMAP port     | Default `1143`                                                     |
| IMAP username | Your Proton email address                                          |
| IMAP password | The **Bridge-generated** password (not your Proton login password) |

### 2. Make Bridge reachable from OpenMates

**Self-hosted (Bridge on same machine):**
`SECRET__PROTONMAIL__BRIDGE_HOST=127.0.0.1` works out of the box.

**Cloud / Docker deployment:**
Bridge must run as a sidecar container or on a host reachable by the `app-mail` container. Set `BRIDGE_HOST` to the container name or IP, and expose the IMAP port internally (do **not** expose it publicly).

### 3. Add env vars to `.env`

```env
# Enable the integration
SECRET__PROTONMAIL__ENABLED=true

# Bridge IMAP credentials (from Bridge Settings → IMAP/SMTP)
SECRET__PROTONMAIL__BRIDGE_HOST=127.0.0.1
SECRET__PROTONMAIL__BRIDGE_IMAP_PORT=1143
SECRET__PROTONMAIL__BRIDGE_USERNAME=you@proton.me
SECRET__PROTONMAIL__BRIDGE_PASSWORD=<bridge-generated-password>

# Which mailbox to search (default: INBOX)
SECRET__PROTONMAIL__MAILBOX=INBOX

# The OpenMates user allowed to use this skill (their OpenMates login email)
SECRET__PROTONMAIL__ALLOWED_OPENMATES_EMAIL=you@example.com
```

> **`ALLOWED_OPENMATES_EMAIL`** is the email address of the OpenMates account (not the Proton address). Only this user will see the mail search skill in the App Store and be able to run it.

### 4. Restart OpenMates

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml \
  up -d app-mail api
```

Vault auto-imports the `SECRET__PROTONMAIL__*` variables on startup — no manual Vault commands needed.

### 5. Verify

Check the provider health in the OpenMates admin health view or via the API:

```bash
GET /v1/health
```

The `providers.protonmail` status should be `healthy`. If it shows `unhealthy`, check:

- Bridge is running and logged in
- `BRIDGE_HOST` is reachable from the `app-mail` container
- `BRIDGE_PASSWORD` is the Bridge-generated password, not your Proton login password

---

## How It Works (User Flow)

1. The configured user opens a chat and asks something like _"search my emails for the latest invoice"_.
2. The `mail.search` skill connects to Bridge over IMAP, fetches matching emails, and sanitizes all content through the prompt-injection protection pipeline before the LLM sees it.
3. Results appear as mail search embed cards in the chat. Clicking one opens a fullscreen reader with the sanitized email body.
4. Email HTML is rendered through DOMPurify (strict allowlist) and all images are proxied — no direct third-party image requests from the browser.

---

## Security Notes

- **Single account only.** The Bridge password grants access to one Proton mailbox. No other users can connect their own accounts.
- **Prompt injection hardening.** All email fields (subject, from, body, snippets) are scanned by the GPT OSS safeguard model before being passed to the LLM.
- **No write access.** The skill is read-only — it can only search and display emails.
- **Access gating is fail-closed.** If `ALLOWED_OPENMATES_EMAIL` is not set or doesn't match the requesting user, the skill is hidden and execution is denied even if called directly.
- **Images proxied.** Email HTML images are rewritten to route through the OpenMates preview server — no tracking pixels or external image requests leave the browser directly.

---

## Limitations

| Limitation                 | Notes                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------ |
| One account per deployment | Bridge supports multiple accounts, but OpenMates uses only the single configured one |
| INBOX only by default      | Set `SECRET__PROTONMAIL__MAILBOX` for a different folder                             |
| Max 50 results per query   | Hard limit to keep responses manageable                                              |
| No sending                 | The skill is read-only                                                               |
| Bridge must stay running   | If Bridge stops, the health check goes `unhealthy` and the skill returns an error    |
