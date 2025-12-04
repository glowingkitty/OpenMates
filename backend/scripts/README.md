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

