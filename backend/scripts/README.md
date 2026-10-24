# Server Debugging Scripts

This directory contains utility scripts for server maintenance, debugging, and administrative tasks.

## Available Scripts

### Show Last Signed Up User

**Purpose:** Display information about the most recently signed up user(s) with decrypted server-side data.

**Command:**
```bash
# Show the most recent user
docker exec -it api python /app/backend/scripts/show_last_user.py

# Show the last 5 users
docker exec -it api python /app/backend/scripts/show_last_user.py --count 5
```

**What it shows:**
- User ID, username (decrypted), admin status
- Creation date and last access time
- Credits, gifted credits, invoice counter (all decrypted)
- Language, dark mode, 2FA status
- Subscription information (if applicable)
- Auto top-up settings (if enabled)
- Profile image URL, last opened page
- Authentication methods count

**Use case:** Debugging user signup issues, checking user data after registration.

---

### Show User Statistics

**Purpose:** Display overall user statistics and database health metrics.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/show_user_stats.py
```

**What it shows:**
- Total user count
- Admin vs regular user counts
- Recent signups (24h, 7d, 30d)
- Active users (24h, 7d, 30d)

**Use case:** Quick health check, monitoring user growth, debugging signup/activity issues.

---

### Server Statistics Overview

**Purpose:** Display comprehensive server-wide statistics including growth, engagement, financial metrics, and detailed usage breakdown.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/server_stats.py

# Show custom timeframe (e.g., last 8 weeks and 12 months)
docker exec -it api python /app/backend/scripts/server_stats.py --weeks 8 --months 12
```

**What it shows:**
- **User Growth & Engagement:** Total users, finished signups (based on actual purchases), conversion funnel status, and subscription/auto top-up counts.
- **Financial Overview:** Total income (last 6 months), ARPU (Average Revenue Per User), and outstanding credit liability (User + Creator).
- **Usage by Skill (Current Month):** Detailed breakdown of credits and request counts for every app skill (e.g., `ai.ask`, `web.search`).
- **Monthly Development:** 6-month trend of Income, Credits Sold, Credits Used, and total Request counts.
- **Weekly Development:** 4-week trend of Income and Credits Sold.

**Use case:** Business monitoring, tracking feature popularity, financial reporting, and estimating profit margins.

---

### Show User Chats

**Purpose:** Display chat information for a specific user.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/show_user_chats.py <user_id>
```

**Example:**
```bash
docker exec -it api python /app/backend/scripts/show_user_chats.py abc12345-6789-0123-4567-890123456789
```

**What it shows:**
- Total chat count for the user
- Total unread messages
- List of recent chats (up to 10) with:
  - Chat ID
  - Creation date
  - Last update time
  - Last message timestamp
  - Unread count

**Use case:** Debugging chat-related issues, verifying user has chats before deletion, investigating sync problems.

---

### Delete User Account by Email

**Purpose:** Delete a user account by email address. Performs the same deletion process as when a user manually deletes their account via the Settings UI.

**Command:**
```bash
# Interactive mode (prompts for confirmation):
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com

# Dry-run mode (preview without actually deleting):
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com --dry-run

# Skip confirmation (for scripted use - USE WITH CAUTION):
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com --yes

# With custom deletion reason (for compliance logging):
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com --reason "Policy violation"
```

**What it does:**
- Hashes the email using SHA-256 (same as frontend during signup - never logs plaintext)
- Looks up user by hashed email
- Shows preview of what will be deleted (passkeys, API keys, chats, etc.)
- Shows credit balance and refundable credits
- Triggers the same Celery deletion task used by the UI
- Auto-refunds ALL unused purchased credits (except gifted/gift card credits)

**Options:**
- `--email`: Email address of the user to delete (required)
- `--dry-run`: Preview what would be deleted without actually deleting
- `--yes, -y`: Skip confirmation prompt (use with caution)
- `--reason`: Reason for deletion (for compliance logging)
- `--deletion-type`: Type of deletion (admin_action, policy_violation, user_requested)
- `--verbose, -v`: Enable verbose/debug logging

**Use case:** Admin-initiated account deletion for policy violations, user requests via support, or GDPR compliance.

---

### Delete Users Without Chats

**Purpose:** Remove users who have no chats created in the system.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/delete_users_without_chats.py
```

**What it does:**
- Fetches all users from Directus
- Checks each user for chats (using hashed_user_id)
- Identifies users without any chats
- Prompts for confirmation before deletion
- Deletes confirmed users

**Safety:** Admin users are automatically skipped. Requires explicit confirmation before deletion.

**Documentation:** See [README_delete_users_without_chats.md](./README_delete_users_without_chats.md) for detailed information.

---

### Send Newsletter

**Purpose:** Send newsletter emails to all confirmed newsletter subscribers.

**Command:**
```bash
# Send newsletter to all subscribers using default template
docker exec -it api python /app/backend/scripts/send_newsletter.py

# Send newsletter using specific template
docker exec -it api python /app/backend/scripts/send_newsletter.py --template newsletter-monthly

# Dry run (test without sending emails)
docker exec -it api python /app/backend/scripts/send_newsletter.py --dry-run

# Test with limited number of subscribers
docker exec -it api python /app/backend/scripts/send_newsletter.py --limit 5
```

**What it does:**
- Fetches all confirmed newsletter subscribers from Directus
- Decrypts their email addresses
- Checks if emails are in the ignored list (skips if ignored)
- Sends newsletter emails to each subscriber using the specified template
- Provides progress feedback and error handling
- Displays summary statistics after completion

**Options:**
- `--template`: Name of the email template to use (default: "newsletter")
- `--dry-run`: Simulate sending without actually sending emails (useful for testing)
- `--limit`: Limit the number of subscribers to process (useful for testing)

**Use case:** Sending monthly newsletters, announcements, or updates to all newsletter subscribers.

**Note:** The script uses the `newsletter.mjml` template by default. You can customize the template or create new templates in `/backend/core/api/templates/email/`. The template receives context variables including `unsubscribe_url`, `darkmode`, and any custom variables you add to the script.

---

### Inspect User

**Purpose:** Display detailed information about a specific user based on their email address, including metadata, decrypted sensitive fields, related item counts, recent activities, and cache status.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/inspect_user.py <email_address>

# With options
docker exec -it api python /app/backend/scripts/inspect_user.py user@example.com --recent-limit 10
docker exec -it api python /app/backend/scripts/inspect_user.py user@example.com --json
docker exec -it api python /app/backend/scripts/inspect_user.py user@example.com --no-cache
```

**What it shows:**
- **User Metadata (Directus):** ID, Account ID, status, admin status, signup completion, last online (relative time), last opened page, and Vault key information.
- **Decrypted Fields (Vault):** Username, credit balance, 2FA secret (masked), 2FA app name, invoice counter, and other sensitive fields decrypted using the user's specific Vault key.
- **Item Counts (Directus):** Total counts for chats, embeds, usage entries, invoices, API keys, passkeys, and gift cards.
- **Recent Activities (Directus):**
  - Most recent chats with IDs and update timestamps.
  - Most recent embeds with IDs and status.
  - Most recent usage entries with IDs, app/skill info, and associated Chat ID (clearly marks REST API calls).
  - Most recent invoices with Order IDs.
- **Cache Status (Redis):** Primed status, chat list count, active LRU chats, and a sample of related cache keys.

**Options:**
- `--recent-limit N`: Limit number of recent activities to display (default: 5).
- `--json`: Output as JSON instead of formatted text.
- `--no-cache`: Skip cache checks (faster if Redis is unavailable).

**Use case:** Comprehensive user debugging, investigating account status, verifying credit balances, checking recent user activity across different services, and identifying cache inconsistencies.

---

### Inspect Chat

**Purpose:** Display detailed information about a specific chat including metadata, messages, embeds, usage entries, and cache status.

**Command:**
```bash
docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id>

# With options
docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --messages-limit 50
docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --json
docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --no-cache
```

**What it shows:**
- Chat metadata from Directus (hashed user ID, timestamps, versions, sharing status)
- Messages with role distribution and encrypted content status
- Embeds with encryption keys status
- Usage entries (credit consumption)
- Redis cache status (versions, messages, drafts, etc.)
- Version consistency checks between Directus and cache

**Options:**
- `--messages-limit N`: Limit number of messages to display (default: 20)
- `--embeds-limit N`: Limit number of embeds to display (default: 20)
- `--usage-limit N`: Limit number of usage entries to display (default: 20)
- `--json`: Output as JSON instead of formatted text
- `--no-cache`: Skip cache checks (faster if Redis is unavailable)

**Use case:** Debugging chat sync issues, investigating message delivery problems, checking cache consistency.

---

### Inspect Demo Chat

**Purpose:** Display detailed information about a demo chat including metadata, translations, messages, embeds, and cache status. Demo chats are public example conversations shown to non-authenticated users.

**Command:**
```bash
# By display ID (demo-1, demo-2, etc.)
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1

# By UUID
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py <uuid>

# With options
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --lang de
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --json
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --no-cache
```

**What it shows:**
- Demo chat metadata from Directus (UUID, status, approval info, encrypted fields)
- All language translations with encrypted fields presence
- Messages filtered by language with role distribution
- Embeds (NOT translated - stored only once with language="original")
- Redis cache status for demo chat data and lists

**Options:**
- `--lang LANG`: Language to inspect (default: en)
- `--messages-limit N`: Limit number of messages to display (default: 20)
- `--embeds-limit N`: Limit number of embeds to display (default: 20)
- `--json`: Output as JSON instead of formatted text
- `--no-cache`: Skip cache checks (faster if Redis is unavailable)

**Use case:** Debugging demo chat display issues, verifying translations, checking if encrypted fields are properly stored.

---

### Inspect Last AI Requests (Debug)

**Purpose:** Inspect the last 10 AI request processing cycles with FULL input/output data for preprocessor, main processor, and postprocessor stages. Essential for debugging AI behavior and understanding the decision-making process.

**Command:**
```bash
# Save all recent requests to YAML
docker exec -it api python /app/backend/scripts/inspect_last_requests.py

# Filter by chat ID
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id <chat_id>

# Custom output path
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --output /tmp/debug.yml
```

**What it captures (FULL content for each request):**

**Preprocessor:**
- Input: Full message history, user preferences, skill config, discovered apps
- Output: Can proceed flag, selected model, category, harmful content score, preselected skills, chat summary, title

**Main Processor:**
- Input: Full preprocessing result, message history count, discovered apps, always-include skills
- Output: Full AI response text, response length, revoked/soft-limited flags

**Postprocessor:**
- Input: Full user message, full assistant response, chat summary, chat tags, available apps
- Output: Follow-up suggestions, new chat suggestions, harmful response score, recommended apps

**Output:**
- Saves to `/app/backend/scripts/debug_output/last_requests_<timestamp>.yml`
- Requests are sorted chronologically (oldest first) so you can follow the conversation flow
- Contains complete data for debugging the AI decision process
- Data auto-expires after 30 minutes in cache

**Copy to host machine:**
```bash
docker cp api:/app/backend/scripts/debug_output/last_requests_<timestamp>.yml ./debug.yml
```

**Options:**
- `--chat-id`: Filter by chat ID
- `--output, -o`: Custom output file path

**Use case:** Understanding why the AI made specific decisions, debugging tool selection, investigating preprocessing failures, analyzing response quality issues.

**Note:** Debug data is encrypted in cache with a system-level Vault key and auto-expires after 30 minutes for privacy.

---

### Translate Text

**Purpose:** Translate text to multiple languages using Gemini 3 Flash with efficient batch translation (all languages in one API call). Supports both plain text and Tiptap JSON format.

**Command:**
```bash
# Translate simple text to all 20 supported languages
docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello, world!"

# Translate to specific languages
docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello, world!" --languages de es fr

# Translate Tiptap JSON (preserves structure, only translates text values)
docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Hello"}]}]}' --json

# Output as JSON format
docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello" --json-output
```

**What it does:**
- Uses Gemini 3 Flash with function calling for efficient batch translation
- Translates to all 20 supported languages in a single API call (much faster than individual calls)
- For Tiptap JSON: Preserves JSON structure, formatting marks, and keys - only translates `text` values
- Validates JSON output for Tiptap translations
- Supports both human-readable and JSON output formats

**Supported languages (20 total):**
`en`, `de`, `zh`, `es`, `fr`, `pt`, `ru`, `ja`, `ko`, `it`, `tr`, `vi`, `id`, `pl`, `nl`, `ar`, `hi`, `th`, `cs`, `sv`

**Options:**
- `--languages LANG [LANG ...]`: Target languages to translate to (default: all 20 languages)
- `--json`: Treat input as Tiptap JSON instead of plain text
- `--json-output`: Output results as JSON instead of human-readable format

**Example output (plain text):**
```
Original text: Hello, how can I help you today?
================================================================================
de : Hallo, wie kann ich Ihnen heute helfen?
es : Hola, ¿cómo puedo ayudarle hoy?
fr : Bonjour, comment puis-je vous aider aujourd'hui ?
================================================================================
```

**Example output (Tiptap JSON):**
```
Original text: {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"This is a test"}]}]}
================================================================================
de : Dies ist ein Test
es : Esta es una prueba
fr : Ceci est un test
================================================================================
```

**Use case:** 
- Testing translation quality before approving community chat suggestions
- Ad-hoc translation needs for content creation
- Verifying Tiptap JSON translation preserves structure correctly
- Quick translation checks during development

**Performance:** Uses batch translation with function calling - translates all languages in one API call instead of 20 separate calls, resulting in ~20x faster translation and lower API costs.

---

### Saved Leaderboard Parsing

Live leaderboard collection is unavailable. The ranking utilities retain parsers,
validation, and formatting for existing local snapshots; they do not refresh data.

| Module | Retained offline parsing functions | Saved data |
|--------|------------------------------------|------------|
| `fetch_openrouter_rankings.py` | `parse_leaderboard`, `parse_top_apps`, `parse_category_leaderboard`, `parse_basic_html` | Model usage and app ranking tables |
| `fetch_lmarena_rankings.py` | `parse_lmarena_markdown` | Model preference scores, vote counts, and organizations |
| `fetch_simplebench_rankings.py` | `parse_simplebench_markdown` | Reasoning scores and optional human baseline |

Call these functions with existing local text. Their validation and output helpers
can inspect or format the parsed records without collecting new rankings.
The `fetch_*` collection functions report that no supported data source is configured.

Stored ranking records remain readable. Daily and startup refreshes are disabled,
and queued refresh jobs report unavailable. Interpret saved scores using their
recorded timestamps; these utilities do not supply current leaderboard results.

---

## Running Scripts

All scripts in this directory should be executed inside the Docker container to ensure:
- Access to environment variables
- Proper service connections
- Correct Python path and dependencies

**General command format:**
```bash
docker exec -it api python /app/backend/scripts/<script_name>.py
```

## Prerequisites

- Docker and Docker Compose must be running
- The `api` service container must be running
- Environment variables must be configured in `.env` file

## Notes

⚠️ **Warning:** These scripts perform administrative operations that may modify or delete data. Always:
- Review what the script will do before running
- Test in a development environment first
- Consider backing up data before destructive operations
- Monitor the execution for errors

