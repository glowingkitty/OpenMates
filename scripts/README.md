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

## Server-Side Scripts

For server-side debugging and administrative scripts, see [`backend/scripts/README.md`](../backend/scripts/README.md).
