# Helper Scripts

This directory contains utility scripts to help with development, code quality, and maintenance tasks.

## Available Scripts

### `find_large_files.sh`

Find all files with more than a specified number of lines. Useful for identifying files that may need refactoring. The script separates i18n YAML files from other code files for easier review.

**Usage:**

```bash
# Find files with more than 500 lines (default)
./scripts/find_large_files.sh

# Find files with more than 1000 lines
./scripts/find_large_files.sh 1000
```

**Features:**

- Excludes log files, binary files, JSON files from locales folder, and Jupyter notebook files
- Separates results into two lists:
  - i18n YAML files
  - Other code files
- Results are sorted by line count (descending)

### `lint_changed.sh`

Lint only the files that have been changed (uncommitted or staged). Automatically detects Python, TypeScript, and Svelte files and runs appropriate linters.

**Usage:**

```bash
./scripts/lint_changed.sh
```

**Features:**

- Automatically detects changed files from git
- Runs appropriate linters based on file type:
  - Python: ruff, mypy
  - TypeScript/Svelte: ESLint, Svelte Check
- Only processes files that have been modified

### `docker-cleanup.sh`

Clean up Docker resources (containers, images, volumes) to free up disk space.

**Usage:**

```bash
./scripts/docker-cleanup.sh
```

### `check_og_tags.py`

Check Open Graph tags for shared chats and embeds.

**Usage:**

```bash
python scripts/check_og_tags.py
```

### `delete_user_account.py`

Admin helper script to delete a user account by email address. Performs the same deletion process as when a user manually deletes their account via the Settings UI.

**Security Features:**
- Email is hashed using Vault HMAC before lookup (never stored/logged in plaintext)
- Requires explicit confirmation before deletion
- Supports dry-run mode to preview what would happen

**Usage:**

```bash
# Must be run from within a Docker container with access to backend services

# Interactive mode (prompts for confirmation):
docker compose exec backend python scripts/delete_user_account.py --email user@example.com

# Dry-run mode (preview without actually deleting):
docker compose exec backend python scripts/delete_user_account.py --email user@example.com --dry-run

# Skip confirmation (for scripted use - USE WITH CAUTION):
docker compose exec backend python scripts/delete_user_account.py --email user@example.com --yes

# With custom deletion reason (for compliance logging):
docker compose exec backend python scripts/delete_user_account.py --email user@example.com --reason "Policy violation"
```

**Options:**
- `--email`: Email address of the user to delete (required)
- `--dry-run`: Preview what would be deleted without actually deleting
- `--yes, -y`: Skip confirmation prompt (use with caution)
- `--reason`: Reason for deletion (for compliance logging)
- `--deletion-type`: Type of deletion (admin_action, policy_violation, user_requested)
- `--verbose, -v`: Enable verbose/debug logging

**Note:** Eligible purchases from the last 14 days are always automatically refunded (except gift card credits).

## Server-Side Scripts

For server-side debugging and administrative scripts, see [`backend/scripts/README.md`](../backend/scripts/README.md).
