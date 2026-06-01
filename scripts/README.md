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
  - Python: ruff (install via `pip install -r backend/requirements-dev.txt`)
  - TypeScript/Svelte: ESLint, Svelte Check
  - YAML: yamllint (install via `pip install -r backend/requirements-dev.txt`)
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

### `linear.py`

Manage Linear issues through the Linear API when MCP access is unavailable. The
script reads `LINEAR_API_KEY` from the environment and never stores it.

**Usage:**

```bash
export LINEAR_API_KEY="<token>"
python3 scripts/linear.py teams
python3 scripts/linear.py list --team OPE --state Todo --query "sync"
python3 scripts/linear.py search "sync" --team OPE
python3 scripts/linear.py get OPE-123 --comments
python3 scripts/linear.py create --team OPE --title "Fix: example" --description "Details"
python3 scripts/linear.py update OPE-123 --state "In Progress" --add-label claude-is-working
python3 scripts/linear.py comment OPE-123 --body "Investigation update"
python3 scripts/linear.py delete OPE-123 --yes
```

## Server-Side Scripts

For server-side debugging and administrative scripts (including `delete_user_account.py`), see [`backend/scripts/README.md`](../backend/scripts/README.md).
