# Reminder App Architecture

> **Status**: In Development  
> **Last Updated**: 2026-02-04

The Reminder app allows users to schedule reminders that can either create a new chat or send a follow-up message in an existing chat. Reminders support both specific times and random times within configurable windows, with optional repeating schedules.

## Overview

### Core Features

- **Specific Time Reminders**: Set a reminder for an exact date and time
- **Random Time Reminders**: Set a reminder for a random time within a date range, with optional daily time window constraints (e.g., "sometime between Jan 1-7, but only 10am-2pm")
- **New Chat Target**: Reminder creates a new chat with the prompt as context
- **Existing Chat Target**: Reminder sends a follow-up system message in the current chat
- **Repeating Reminders**: Daily, weekly, monthly, or custom interval repeating schedules
- **Email Notification Integration**: Leverages existing notification system; prompts users to set up email notifications if not configured

### Key Architecture Decisions

1. **Cache-First Storage**: Reminders are stored vault-encrypted in Dragonfly cache (not Directus) for performance and simplicity
2. **Disk Spillover**: On graceful shutdown, pending reminders are dumped to disk; restored on startup
3. **Chat History Snapshot**: For existing-chat reminders, chat history is cached with the reminder (since Directus only has client-encrypted data the server cannot read)
4. **System Messages**: Reminders deliver as system messages, rendered specially by the frontend

## Data Model

### Reminder Cache Entry

```python
{
    # Identity
    "reminder_id": str,          # UUID, primary key
    "user_id": str,              # For vault_key_id lookup and WebSocket routing
    "vault_key_id": str,         # User's vault key for decryption

    # Encrypted Content (vault-encrypted with user's key)
    "encrypted_prompt": str,             # The reminder message/prompt
    "encrypted_chat_history": str | None, # Only for existing_chat target (JSON array)
    "encrypted_new_chat_title": str | None, # Only for new_chat target

    # Trigger Configuration
    "trigger_type": "specific" | "random",
    "trigger_at": int,           # Unix timestamp - calculated at creation

    # For random triggers (stored for recalculation on repeat)
    "random_config": {
        "start_date": str,       # YYYY-MM-DD
        "end_date": str,         # YYYY-MM-DD
        "time_window_start": str, # HH:MM (24h format)
        "time_window_end": str,   # HH:MM (24h format)
        "timezone": str           # e.g., "Europe/Berlin"
    } | None,

    # Target Configuration
    "target_type": "new_chat" | "existing_chat",
    "target_chat_id": str | None,  # Only for existing_chat

    # Repeat Configuration
    "repeat_config": {
        "type": "daily" | "weekly" | "monthly" | "custom",
        "interval": int | None,      # For custom: every N units
        "interval_unit": "days" | "weeks" | "months" | None,
        "day_of_week": int | None,   # For weekly: 0=Monday, 6=Sunday
        "day_of_month": int | None,  # For monthly: 1-31
        "time_of_day": str,          # HH:MM - time for repeating reminders
        "end_date": str | None,      # Optional end date
        "max_occurrences": int | None # Optional max repeat count
    } | None,

    # Metadata
    "created_at": int,           # Unix timestamp
    "created_in_chat_id": str,   # Chat where reminder was created
    "occurrence_count": int,     # Times fired (for repeating)

    # Status
    "status": "pending" | "fired" | "cancelled"
}
```

### Cache Key Patterns

| Pattern                    | Type | Description                                                  |
| -------------------------- | ---- | ------------------------------------------------------------ |
| `reminders:schedule`       | ZSET | Score=trigger_at, member=reminder_id (for efficient polling) |
| `reminder:{reminder_id}`   | HASH | Individual reminder data (vault-encrypted)                   |
| `user:{user_id}:reminders` | SET  | User's reminder IDs (for listing)                            |

## Skills

### set-reminder

Schedules a reminder on the server.

**Input Parameters:**

| Field               | Type     | Required    | Description                                 |
| ------------------- | -------- | ----------- | ------------------------------------------- |
| `prompt`            | string   | Yes         | The reminder message/prompt                 |
| `trigger_type`      | enum     | Yes         | `"specific"` or `"random"`                  |
| `trigger_datetime`  | datetime | If specific | ISO 8601 datetime                           |
| `random_start_date` | date     | If random   | Start of random window (YYYY-MM-DD)         |
| `random_end_date`   | date     | If random   | End of random window (YYYY-MM-DD)           |
| `random_time_start` | string   | If random   | Earliest time (HH:MM, 24h)                  |
| `random_time_end`   | string   | If random   | Latest time (HH:MM, 24h)                    |
| `timezone`          | string   | Yes         | User's timezone (e.g., "Europe/Berlin")     |
| `target_type`       | enum     | No          | `"new_chat"` (default) or `"existing_chat"` |
| `new_chat_title`    | string   | If new_chat | Title for the new chat                      |
| `repeat`            | object   | No          | Repeat configuration (see below)            |

**Repeat Configuration:**

| Field             | Type | Required   | Description                                    |
| ----------------- | ---- | ---------- | ---------------------------------------------- |
| `type`            | enum | Yes        | `"daily"`, `"weekly"`, `"monthly"`, `"custom"` |
| `interval`        | int  | If custom  | Repeat every N units                           |
| `interval_unit`   | enum | If custom  | `"days"`, `"weeks"`, `"months"`                |
| `day_of_week`     | int  | If weekly  | 0=Monday, 6=Sunday                             |
| `day_of_month`    | int  | If monthly | 1-31                                           |
| `end_date`        | date | No         | Stop repeating after this date                 |
| `max_occurrences` | int  | No         | Maximum repeat count                           |

**Behavior:**

1. Validates input parameters
2. Checks if user has email notifications configured; if not, includes recommendation in response
3. Calculates `trigger_at` timestamp:
   - Specific: Parse datetime, convert to UTC
   - Random: Pick random day in range, then random time within daily window
4. If `target_type == "existing_chat"`:
   - Fetches current chat history from AI cache
   - Vault-encrypts and stores with reminder
5. Vault-encrypts prompt and new_chat_title
6. Creates reminder entry in cache
7. Returns confirmation with reminder details

### list-reminders

Lists the user's reminders.

**Input Parameters:**

| Field    | Type | Required | Description                      |
| -------- | ---- | -------- | -------------------------------- |
| `status` | enum | No       | `"pending"` (default) or `"all"` |

**Returns:** List of reminders with decrypted prompts and trigger times.

### cancel-reminder

Cancels a pending reminder.

**Input Parameters:**

| Field         | Type   | Required | Description                  |
| ------------- | ------ | -------- | ---------------------------- |
| `reminder_id` | string | Yes      | ID of the reminder to cancel |

**Behavior:**

1. Validates reminder exists and belongs to user
2. Marks as cancelled
3. Removes from schedule index
4. Returns confirmation

## Processing Architecture

### Celery Beat Schedule

```python
'process-due-reminders': {
    'task': 'reminder.process_due_reminders',
    'schedule': timedelta(seconds=60),  # Every minute
    'options': {'queue': 'reminder'},
}
```

### Reminder Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Every 60 seconds                              │
├─────────────────────────────────────────────────────────────────┤
│  1. Query ZSET: ZRANGEBYSCORE reminders:schedule 0 {now}        │
│  2. For each due reminder:                                       │
│     ├─ Decrypt prompt (and chat_history if existing_chat)       │
│     ├─ Execute target action:                                    │
│     │   ├─ new_chat: Create chat + system message               │
│     │   └─ existing_chat: Restore history + system message      │
│     ├─ Send notification (WebSocket + email if configured)      │
│     ├─ If repeating:                                            │
│     │   ├─ Calculate next trigger_at                            │
│     │   ├─ Update ZSET score                                    │
│     │   └─ Increment occurrence_count                           │
│     └─ If one-time: Delete reminder                             │
└─────────────────────────────────────────────────────────────────┘
```

### Target Actions

**New Chat:**

1. Generate new `chat_id` (UUID)
2. Create chat in Directus (encrypted title)
3. Create system message with reminder prompt
4. Update user's sync cache
5. Notify via WebSocket: `new_chat_from_reminder` event
6. Send email notification if configured

**Existing Chat:**

1. Restore cached chat history to AI cache
2. Create system message with reminder prompt
3. Update chat's sync cache
4. Notify via WebSocket: `reminder_message` event
5. Send email notification if configured

## System Message Format

Reminder messages use a distinctive format:

```
🔔 **Reminder**

{prompt}

---
*Reminder set on {created_date}*
```

- Role: `system`
- Includes metadata identifying it as a reminder
- Frontend renders as a notification card

## Disk Spillover (Persistence Safety)

### Backup File

Location: `/shared/cache/pending_reminders_backup.json`

```json
{
  "timestamp": 1704067200,
  "version": 1,
  "reminders": [
    {
      "reminder_id": "...",
      "user_id": "...",
      "vault_key_id": "...",
      "encrypted_prompt": "...",
      "trigger_at": 1704153600,
      ...
    }
  ]
}
```

### Lifecycle Hooks

- **Startup**: `cache_service.restore_reminders_from_disk()` - Restore pending reminders
- **Shutdown**: `cache_service.dump_reminders_to_disk()` - Save pending reminders

## WebSocket Events

| Event                    | Payload                                  | Description                |
| ------------------------ | ---------------------------------------- | -------------------------- |
| `new_chat_from_reminder` | `{chat_id, title, reminder_id}`          | New chat created           |
| `reminder_message`       | `{chat_id, message_id, reminder_id}`     | Follow-up in existing chat |
| `reminder_scheduled`     | `{reminder_id, trigger_at, target_type}` | Confirmation               |
| `reminder_cancelled`     | `{reminder_id}`                          | Cancellation confirmation  |

## Integration Points

### Email Notifications

The reminder app integrates with the existing notification system:

- Checks if user has email notifications configured
- If not, skill response includes recommendation to set up email
- When reminder fires, sends email notification via existing email service

### Other Apps

The reminder app can be used by other apps for scheduled actions:

- **Shopping App**: Reminders to reconsider purchase decisions
- **Health App**: Appointment reminders
- **Plant Parent App**: Watering schedule reminders
- **Travel App**: Trip preparation reminders

## File Structure

```
backend/apps/reminder/
├── __init__.py
├── app.yml                      # App configuration
├── skills/
│   ├── __init__.py
│   ├── set_reminder_skill.py    # Create reminders
│   ├── list_reminders_skill.py  # List user's reminders
│   └── cancel_reminder_skill.py # Cancel reminders
├── tasks.py                     # Celery tasks
└── utils.py                     # Time calculation helpers

backend/core/api/app/services/
└── cache_reminder_mixin.py      # Cache operations

frontend/packages/ui/src/i18n/sources/
└── reminder.yml                 # Translations
```

## Security Considerations

1. **Vault Encryption**: All sensitive data (prompt, chat history) encrypted with user's vault key
2. **User Isolation**: Users can only access their own reminders
3. **No Plaintext Storage**: Server never stores plaintext reminder content
4. **Auto-Deletion**: Reminders deleted after firing (except repeating)
5. **Disk Backup Encryption**: Backup file contains vault-encrypted data only

## Error Handling

| Scenario                       | Action                                          |
| ------------------------------ | ----------------------------------------------- |
| User deleted                   | Skip reminder, log warning, delete entry        |
| Vault key issue                | Retry once, then mark failed, alert admin       |
| Chat not found (existing_chat) | Create as new_chat fallback, notify user        |
| Processing failure             | Retry with exponential backoff (max 3 attempts) |

## Future Enhancements

- **Location-based reminders**: Trigger when user enters/exits a location
- **Smart scheduling**: AI suggests optimal reminder times based on user patterns
- **Snooze functionality**: Allow users to postpone reminders
- **Reminder templates**: Pre-defined reminder patterns for common use cases
