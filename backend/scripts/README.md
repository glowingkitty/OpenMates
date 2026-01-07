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

