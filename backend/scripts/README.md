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

### Fetch OpenRouter Rankings

**Purpose:** Fetch AI model rankings from OpenRouter.ai including the LLM Leaderboard, Top Apps, and Programming category leaderboard.

**Command:**
```bash
# Fetch general LLM leaderboard and Top Apps
docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py

# Fetch with Programming category leaderboard
docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --category programming

# Output as JSON
docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --json

# Save to file
docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --json -o /app/rankings.json

# Basic mode (no Firecrawl, limited to main leaderboard only)
docker exec -it api python /app/backend/scripts/fetch_openrouter_rankings.py --basic
```

**What it shows:**

Without `--category`:
- **General LLM Leaderboard** - Top models by overall token usage this week
- **Top Apps** - Largest public apps using OpenRouter

With `--category programming`:
- **Programming Category Leaderboard** - Top models used specifically for programming tasks
- Different rankings reflecting which models developers prefer for coding

**Example output:**
```
═══════════════════════════════════════════════════════════════════════════
📊 OPENROUTER AI MODEL RANKINGS - PROGRAMMING
═══════════════════════════════════════════════════════════════════════════
Source:   https://openrouter.ai/rankings/programming
Method:   firecrawl
Time:     2026-01-14T12:13:51.420367+00:00
Category: programming
Status:   ✅ Valid

───────────────────────────────────────────────────────────────────────────
📈 PROGRAMMING LEADERBOARD (Token Usage)
───────────────────────────────────────────────────────────────────────────
#    Model                            Provider     Tokens     Share   
1    Grok Code Fast 1                 x-ai         200B       25.1%   
2    Claude Opus 4.5                  anthropic    143B       18.0%   
3    Devstral 2 2512 (free)          mistralai    70.2B      8.8%    
4    Gemini 3 Flash Preview           google       63.3B      8.0%    
5    Claude Sonnet 4.5               anthropic    62.2B      7.8%    
...
```

**Validation:** The script validates output and warns if the scraper may be broken:
```
⚠️  Warnings (1):
   - NO_CATEGORY_DATA: 'programming' leaderboard empty - scraper may be broken
```

**Options:**
- `--category, -c CAT`: Fetch category-specific leaderboard (only `programming` is reliably available)
- `--json`: Output as JSON instead of formatted text
- `-o, --output FILE`: Save output to file
- `--basic`: Use basic HTML parsing (no Firecrawl, limited data)

**Known Limitation:** OpenRouter's rankings page is a Single Page Application (SPA). The Categories section always defaults to showing "Programming" data regardless of the URL path. Other categories (roleplay, legal, marketing, etc.) cannot be reliably fetched because the UI dropdown doesn't auto-select based on the URL.

**Note:** Uses Firecrawl API (key from Vault) to render JavaScript. Without Firecrawl (`--basic`), only the general leaderboard is available.

---

### Fetch LMArena Rankings

**Purpose:** Fetch AI model rankings from LMArena.ai (LMSYS Chatbot Arena) based on human preference votes using Elo ratings.

**Command:**
```bash
# Fetch overall text leaderboard (default)
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py

# Fetch coding category leaderboard
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --category coding

# Output as JSON
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --json

# Save to file
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py -o /app/lmarena.json

# List all available categories
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --list-categories

# Limit results
docker exec -it api python /app/backend/scripts/fetch_lmarena_rankings.py --limit 20
```

**What it shows:**
- Model rankings based on Elo scores (human preference votes)
- Vote counts per model
- Organization/provider information
- Data quality validation metrics

**Available categories:**
- Main: `text`, `webdev`, `vision`, `text-to-image`, `image-edit`, `search`, `text-to-video`, `image-to-video`
- Text subcategories: `overall`, `hard-prompts`, `coding`, `math`, `creative-writing`, `instruction-following`, `longer-query`
- Aliases: `code` → coding, `writing` → creative-writing

**Options:**
- `--category, -c CAT`: Category to fetch (default: text)
- `--limit, -n N`: Max models to return (default: 50)
- `--json, -j`: Output as JSON
- `-o, --output FILE`: Save output to file
- `--list-categories, -l`: List all available categories

**Validation:** Includes comprehensive validation with data quality metrics:
- Completeness percentage (required fields)
- Vote count coverage
- Organization coverage
- Expected model families found
- Score range validation

**Note:** LMArena has NO official API - uses Firecrawl to render JavaScript. Cloudflare protection may occasionally block requests.

**Documentation:** See [LMARENA_RANKINGS_README.md](./LMARENA_RANKINGS_README.md) for detailed documentation.

---

### Fetch SimpleBench Rankings

**Purpose:** Fetch AI model rankings from SimpleBench (simple-bench.com), a multiple-choice reasoning benchmark where non-specialized humans outperform frontier LLMs.

**Command:**
```bash
# Fetch SimpleBench leaderboard
docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py

# Output as JSON
docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py --json

# Save to file
docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py -o /app/simplebench.json

# Include human baseline in results
docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py --include-human

# Limit results
docker exec -it api python /app/backend/scripts/fetch_simplebench_rankings.py --limit 20
```

**What it shows:**
- Model rankings by percentage score
- Organization/provider for each model
- Human baseline comparison (83.7%)
- Validation warnings if data quality issues detected

**Example output:**
```
================================================================================
SIMPLEBENCH LEADERBOARD - AI Reasoning Benchmark
Source: https://simple-bench.com/
Fetched: 2026-01-14 12:30:35 UTC
================================================================================

Rank   Model                                    Score        Organization        
--------------------------------------------------------------------------------
#1     Gemini 3 Pro Preview                     76.4%        Google              
#2     Gemini 2.5 Pro (06-05)                   62.4%        Google              
#3     Claude Opus 4.5                          62.0%        Anthropic           
#4     GPT-5 Pro                                61.6%        OpenAI              
...
```

**Options:**
- `--json`: Output as JSON instead of formatted text
- `-o, --output FILE`: Save output to file
- `--limit N`: Max models to return (default: 100)
- `--include-human`: Include human baseline in results (rank 0)

**Note:** SimpleBench tests spatio-temporal reasoning, social intelligence, and linguistic adversarial robustness where humans significantly outperform current AI models.

---

## Leaderboard Scripts Quick Reference

| Script | Source | Data Type | Command |
|--------|--------|-----------|---------|
| OpenRouter | openrouter.ai | API usage (tokens) | `fetch_openrouter_rankings.py` |
| LMArena | lmarena.ai | Human votes (Elo) | `fetch_lmarena_rankings.py` |
| SimpleBench | simple-bench.com | Reasoning benchmark | `fetch_simplebench_rankings.py` |

All three scripts require:
- Running inside Docker container (`docker exec -it api python ...`)
- Firecrawl API key (configured in Vault)

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

