---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/apps_api.py
  - backend/apps/base_skill.py
---

# Action Confirmation

> Different security models for write/sensitive operations: web app requires user confirmation, programmatic access (REST API/CLI) uses layered security without confirmation.

## Why This Exists

Write operations (send email, create calendar event, delete file) need safeguards. The web app uses real-time confirmation because the user is present; programmatic access skips confirmation for automation usability but compensates with scoped keys, rate limiting, and logging.

## How It Works

### Web App: Confirmation Flow

1. **Classification:** Server checks if skill requires confirmation. If Autonomous Mode is enabled and the skill doesn't have "Always Require Confirmation", skip to execution.
2. **Queue:** Create pending skill record with unique `app_skill_id`, confirmation token, and expiration (default 5 min).
3. **Notify:** WebSocket `app_skill_confirmation_required` to all user devices.
4. **User confirms:** Via embedded preview UI (same location as normal skill results). Options: individual approve/reject per skill, or "Approve All" for grouped skills.
5. **Execute or cancel:** Based on approval, rejection, or expiration.

### Web App: Autonomous Mode

- Toggle in Settings header; default disabled
- When enabled: auto-confirms all skills without user confirmation
- Per-skill override: `Settings > App Store > [App] > [Skill] > Always Require Confirmation`
- All auto-confirmed actions still logged

### Web App: Offline Handling

- Skills remain queued until user comes online (default 30-min timeout)
- On reconnect: pending skills re-notified
- History viewable in Settings

### REST API / CLI / SDK: No Confirmation

Security provided through layered controls:

1. **API key scopes** -- keys scoped to specific apps/skills, limiting compromise damage
2. **Rate limiting** -- write actions rate-limited (e.g., 10 writes/min per key); tracked per provider/skill/model
3. **Privacy-compliant logging** -- minimal by default (skill ID, timestamp, key hash, status). No sensitive data logged unless user opts into enhanced logging. GDPR-compliant with deletion rights.
4. **Device confirmation** -- new devices must be approved before API access
5. **Optional enhanced security** -- users can enable "Require confirmation for all API actions" in Developer Settings, which queues API writes for WebSocket confirmation

### Implementation Details

- Pending skills stored in Redis/Dragonfly with TTL: `pending_app_skill:{user_id}:{app_skill_id}`
- WebSocket confirmation broadcasts to all connected devices; confirmation can come from any device
- Confirmation tokens are cryptographically secure; skill details are signed to prevent tampering

### Skill Configuration

Confirmation requirements defined per skill in app configuration. Users can override per-app or per-skill in `Settings > App Store`. Examples:
- Requires confirmation: `email.send`, `calendar.create_event`, `code.delete_file`
- No confirmation: `web.search`, `videos.get_transcript`, `calendar.read_events`

## Related Docs

- [REST API](./rest-api.md) -- API endpoints and authentication
- [CLI Package](./cli-package.md) -- SDK access patterns
