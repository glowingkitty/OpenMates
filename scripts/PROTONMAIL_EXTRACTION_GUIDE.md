# ProtonMail Email Extraction Guide

This guide explains how to extract text from ProtonMail support/issue emails for LLM processing. Two approaches are available:

## Option 1: ProtonMail Export Tool (Recommended for One-Time Task)

This is the **easiest and most reliable** method for a one-time extraction.

### Prerequisites
- ProtonMail account (any plan)
- ProtonMail Export Tool (free, official)

### Step-by-Step Instructions

#### 1. Download and Install ProtonMail Export Tool

1. Visit: https://proton.me/support/proton-mail-export-tool
2. Download the tool for your operating system (Windows, macOS, or Linux)
3. Extract the archive to a location of your choice

#### 2. Export Your Emails

1. Run the ProtonMail Export Tool
2. Log in with your ProtonMail credentials
3. Choose the backup/export option
4. Select the location where you want to save the exported emails
5. Wait for the export to complete (this may take a while depending on the number of emails)
6. The tool will create:
   - A folder with `.eml` files (one per email)
   - JSON metadata files

#### 3. Extract Text Using the Script

Once you have the exported EML files, use the parsing script:

```bash
# Basic usage - extract all emails
python scripts/parse_protonmail_export.py --export-dir /path/to/exported/emails

# Filter by subject keywords (e.g., "support", "issue", "help")
python scripts/parse_protonmail_export.py \
    --export-dir /path/to/exported/emails \
    --filter-subject "support" "issue" "help" \
    --output support_emails.json

# Filter by sender
python scripts/parse_protonmail_export.py \
    --export-dir /path/to/exported/emails \
    --filter-sender "support@protonmail.com" \
    --output support_emails.json

# Output as plain text (easier to read/copy)
python scripts/parse_protonmail_export.py \
    --export-dir /path/to/exported/emails \
    --filter-subject "support" \
    --output support_emails.txt \
    --format text

# Search recursively in subdirectories
python scripts/parse_protonmail_export.py \
    --export-dir /path/to/exported/emails \
    --recursive \
    --output all_emails.json
```

### Script Options

- `--export-dir`: **Required**. Path to directory containing exported EML files
- `--output`: Output file path (default: `extracted_emails.json`)
- `--format`: Output format - `json` or `text` (default: `json`)
- `--filter-subject`: Filter emails by subject keywords (case-insensitive, multiple keywords supported)
- `--filter-sender`: Filter emails by sender keywords (case-insensitive, multiple keywords supported)
- `--recursive`: Search for EML files in subdirectories

### Output Format

**JSON format** (`--format json`):
```json
[
  {
    "file": "email_123.eml",
    "subject": "Support Request",
    "from": "user@example.com",
    "to": "support@protonmail.com",
    "date": "2024-01-15T10:30:00+00:00",
    "text": "Email content here...",
    "text_length": 1234
  }
]
```

**Text format** (`--format text`):
```
================================================================================
Email 1/10
================================================================================
Subject: Support Request
From: user@example.com
Date: 2024-01-15T10:30:00+00:00

Content:
Email content here...

```

---

## Option 2: ProtonMail Bridge + IMAP (For Ongoing Access)

This method requires a **paid ProtonMail account** and allows direct access via IMAP.

### Prerequisites
- ProtonMail paid account (required for Bridge)
- ProtonMail Bridge installed and running
- Python `imaplib` (built-in, no extra dependencies)

### Step-by-Step Instructions

#### 1. Install ProtonMail Bridge

1. Visit: https://proton.me/mail/bridge
2. Download and install ProtonMail Bridge for your OS
3. Launch the Bridge application
4. Log in with your ProtonMail credentials

#### 2. Get IMAP Credentials

1. In ProtonMail Bridge, go to **Settings** or **Account Settings**
2. Find the **IMAP/SMTP** section
3. Note the following:
   - **IMAP Server**: Usually `127.0.0.1` or `localhost`
   - **IMAP Port**: Usually `1143`
   - **Username**: Your full ProtonMail email address
   - **Password**: The Bridge-specific password (different from your ProtonMail password)

#### 3. Fetch Emails Using the Script

```bash
# Basic usage - fetch all emails from INBOX
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com

# Search by subject keyword
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --search-subject "support"

# Search by sender
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --search-sender "support@protonmail.com"

# Fetch from specific folder
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --folder "Support" \
    --output support_emails.json

# Fetch emails from last 30 days only
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --days-back 30 \
    --limit 100

# Output as plain text
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --search-subject "support" \
    --output support_emails.txt \
    --format text
```

### Script Options

- `--imap-host`: IMAP server hostname (default: `localhost`)
- `--imap-port`: IMAP server port (default: `1143`)
- `--username`: **Required**. Your ProtonMail email address
- `--password`: Password (will prompt if not provided)
- `--folder`: Mailbox folder to search (default: `INBOX`)
- `--search-subject`: Search for emails with keyword in subject
- `--search-sender`: Search for emails from specific sender
- `--days-back`: Only fetch emails from last N days
- `--limit`: Maximum number of emails to fetch
- `--output`: Output file path (default: `fetched_emails.json`)
- `--format`: Output format - `json` or `text` (default: `json`)

---

## Quick Start Examples

### Example 1: Extract All Support Emails (Export Method)

```bash
# 1. Export emails using ProtonMail Export Tool (manual step)
# 2. Extract support-related emails
python scripts/parse_protonmail_export.py \
    --export-dir ~/Downloads/protonmail_export \
    --filter-subject "support" "issue" "help" "bug" "problem" \
    --output support_emails.json
```

### Example 2: Extract Recent Support Emails (IMAP Method)

```bash
# Fetch last 50 support emails from last 90 days
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --search-subject "support" \
    --days-back 90 \
    --limit 50 \
    --output recent_support_emails.json
```

### Example 3: Extract All Emails from Specific Sender

```bash
# Using export method
python scripts/parse_protonmail_export.py \
    --export-dir ~/Downloads/protonmail_export \
    --filter-sender "support@protonmail.com" \
    --output protonmail_support.json

# Using IMAP method
python scripts/fetch_protonmail_imap.py \
    --imap-host localhost \
    --imap-port 1143 \
    --username your@email.com \
    --search-sender "support@protonmail.com" \
    --output protonmail_support.json
```

---

## Using the Extracted Data with LLMs

Once you have the extracted emails in JSON or text format, you can:

### Option A: Direct Text Input
```bash
# For small datasets, copy text directly
cat support_emails.txt | pbcopy  # macOS
cat support_emails.txt | xclip   # Linux
```

### Option B: Process with Python Script
Create a simple script to format for LLM:

```python
import json

with open('support_emails.json', 'r') as f:
    emails = json.load(f)

# Combine all email text
combined_text = "\n\n---\n\n".join([
    f"Subject: {e['subject']}\nFrom: {e['from']}\nDate: {e['date']}\n\n{e['text']}"
    for e in emails
])

with open('llm_input.txt', 'w') as f:
    f.write(combined_text)
```

### Option C: Use JSON for Structured Processing
The JSON format allows you to:
- Filter by date ranges
- Group by sender
- Analyze patterns
- Feed to LLM APIs with structured context

---

## Troubleshooting

### Export Tool Issues
- **Export fails**: Ensure you have enough disk space
- **Can't find EML files**: Check subdirectories, use `--recursive` flag
- **Encoding errors**: The script handles most encoding issues automatically

### IMAP/Bridge Issues
- **Connection refused**: Ensure ProtonMail Bridge is running
- **Authentication failed**: Verify Bridge password (not your ProtonMail password)
- **Port issues**: Check Bridge settings for correct port (usually 1143)
- **No emails found**: Try different search terms or check folder name

### Script Issues
- **Import errors**: Ensure you're using Python 3.7+
- **Permission errors**: Make output directory writable
- **Empty results**: Check filter criteria aren't too restrictive

---

## Security Notes

- **Passwords**: Never commit passwords to version control
- **Email content**: Be careful when sharing extracted emails (may contain sensitive data)
- **Bridge credentials**: Store Bridge password securely (use password manager)
- **Output files**: Consider encrypting output files if they contain sensitive information

---

## Comparison: Export vs IMAP

| Feature | Export Tool | IMAP/Bridge |
|---------|-------------|-------------|
| **Account type** | Free or paid | Paid only |
| **Setup complexity** | Low | Medium |
| **One-time use** | ✅ Perfect | ⚠️ Requires Bridge running |
| **Ongoing access** | ❌ Must re-export | ✅ Direct access |
| **Filtering** | After export | During fetch |
| **Speed** | Fast (local files) | Depends on connection |
| **Reliability** | ✅ Very reliable | ⚠️ Depends on Bridge |

**Recommendation for one-time task**: Use the **Export Tool method** - it's simpler, works with any account, and doesn't require keeping Bridge running.


