# Onboarding Architecture

> **Status**: ✅ Implemented
> **Last Updated**: 2026-02-18

## Overview

The onboarding system introduces new users to OpenMates through a pre-configured AI chat guided by "Suki", the onboarding assistant. It runs as the `openmates-welcome` focus mode and collects — with explicit user consent — an anonymous use-case summary that is stored for product insight and emailed to the server admin.

---

## Architecture at a Glance

```
Signup completes (handleAutoTopUpComplete in Signup.svelte)
     │
     ▼
createOnboardingChat()          ← called once; hasOnboardingChat() guards duplicates
     │  Creates a chat in IndexedDB with:
     │  - Static welcome message (no AI, no credits)
     │  - encrypted_active_focus_id = encrypt("openmates-welcome")
     │  - Follow-up suggestion chips
     ▼
User sends first message
     │  client sends active_focus_id: "openmates-welcome" on WebSocket
     ▼
main_processor.py               ← injects "welcome" system prompt into LLM context
     │
     ▼
LLM (Suki) converses            ← understands use case, may call share-usecase skill
     │
     ▼ (if user consents)
ShareUsecaseSkill.execute()
     ├── writes to Directus: onboarding_usecases  (anonymous: no user_id)
     └── dispatches Celery task → sends email to SERVER_OWNER_EMAIL
```

---

## Components

### 1. Welcome Focus Mode (`openmates-welcome`)

**Defined in:** [`backend/apps/openmates/app.yml`](../../backend/apps/openmates/app.yml)

The `welcome` focus mode (full runtime ID: `openmates-welcome`) configures Suki's onboarding persona. When active, Suki:

1. Listens to the user's description of their intended use
2. Introduces 2–3 relevant specialist mates and 1–2 relevant features
3. Summarizes the conversation and offers to share it anonymously with the OpenMates team
4. If the user agrees, calls the `share-usecase` skill

The focus mode's `preprocessor_hint` triggers automatic selection by the AI preprocessor when a user is in a post-signup conversation, or when a user explicitly mentions getting started / asking about features. Users can also activate it manually with `@focus:openmates:welcome`.

**Rules enforced in the system prompt:**

- Responses kept to 3–5 sentences
- One sharing offer only — no pressure
- Off-topic questions are briefly answered, then conversation guided back
- Never mentions technical internals (encryption, WebSockets, APIs)

---

### 2. Onboarding Chat Creation (Frontend)

**Service:** [`frontend/packages/ui/src/services/onboardingChatService.ts`](../../frontend/packages/ui/src/services/onboardingChatService.ts)  
**Called from:** `handleAutoTopUpComplete()` in [`frontend/packages/ui/src/components/signup/Signup.svelte`](../../frontend/packages/ui/src/components/signup/Signup.svelte)

`createOnboardingChat()` runs once after signup and:

1. Generates a new chat UUID and AES-GCM chat key
2. Encrypts the static welcome message (i18n key `onboarding.welcome_message`, interpolated with username)
3. Pre-activates the focus mode by setting `encrypted_active_focus_id = encrypt("openmates-welcome")` directly in IndexedDB — no server round-trip, no countdown shown to user
4. Encrypts 4 follow-up suggestion chips (i18n keys `onboarding.follow_up_1..4`)
5. Encrypts the chat icon `compass`
6. Saves the `Chat` and `Message` to IndexedDB via `addChat()` / `saveMessage()`
7. Dispatches `localChatListChanged` so the chat list refreshes

`hasOnboardingChat()` is also exported — it scans IndexedDB and decrypts `encrypted_active_focus_id` on any chat that has one, returning `true` if `openmates-welcome` is already present. This prevents duplicate creation on page reload.

**Signup wiring:** `handleAutoTopUpComplete` in `Signup.svelte` calls `hasOnboardingChat()` first, then `createOnboardingChat($signupStore.username)` if no chat exists yet. The call is fire-and-forget — a failure does not block signup completion.

---

### 3. Pre-Activated Focus Mode (No Countdown)

For the onboarding chat, the focus mode is pre-activated at chat creation time by the frontend — the `encrypted_active_focus_id` is written to IndexedDB immediately. This bypasses the normal focus mode activation flow (AI tool call → `FocusModeActivationEmbed` 4-second countdown → `focus_mode_auto_confirm_task`).

When the user sends their first message, the client includes `active_focus_id: "openmates-welcome"` in the WebSocket payload. The server's `message_received_handler.py` reads this and passes it to `main_processor.py`, which injects the `welcome` system prompt into the LLM context.

The backend does not have any route that detects or enforces the welcome focus mode specifically — focus mode management is entirely generic.

---

### 4. Share Use-Case Skill

**Defined in:** [`backend/apps/openmates/app.yml`](../../backend/apps/openmates/app.yml)  
**Implementation:** [`backend/apps/openmates/skills/share_usecase_skill.py`](../../backend/apps/openmates/skills/share_usecase_skill.py)

#### Privacy Design

The submission is **fully anonymous by design**:

- Only `summary` (string, 2–5 sentences) and `language` (ISO 639-1 code) are stored
- `user_id` is accepted as a parameter (injected by `BaseApp`) but explicitly **never** written
- The `onboarding_usecases` Directus collection has no `user_id` field at the schema level

#### Validation

- `summary`: required, max 3000 characters
- `language`: validated against ~30 ISO 639-1 codes; unknown codes fall back to `"en"` (graceful, not an error)

#### Storage

On success, writes to the `onboarding_usecases` Directus collection:

| Field       | Value                    |
| ----------- | ------------------------ |
| `summary`   | Anonymous use-case text  |
| `language`  | ISO 639-1 code           |
| `timestamp` | Unix timestamp (seconds) |

Schema defined in: [`backend/core/directus/schemas/onboarding_usecases.yml`](../../backend/core/directus/schemas/onboarding_usecases.yml)

#### Admin Email Notification

After a successful save, the skill dispatches a fire-and-forget Celery task to notify the server admin:

- **Task:** `send_usecase_submitted_notification` in [`backend/core/api/app/tasks/email_tasks/usecase_submitted_email_task.py`](../../backend/core/api/app/tasks/email_tasks/usecase_submitted_email_task.py)
- **Queue:** `email`
- **Recipient:** `SERVER_OWNER_EMAIL` environment variable
- **Template:** [`backend/core/api/templates/email/usecase_submitted.mjml`](../../backend/core/api/templates/email/usecase_submitted.mjml)
- **Content:** summary text and language code only — no user identity
- **Non-fatal:** if `SERVER_OWNER_EMAIL` is unset or `celery_producer` is unavailable, a warning is logged but the user still receives a success response (the submission is already stored)

#### Invocation Paths

The skill can be invoked two ways:

1. **LLM function calling (primary):** Suki's system prompt instructs the LLM to call `share-usecase` after the user explicitly consents. The AI processing pipeline dispatches it to the OpenMates app service.

2. **Direct REST API (external):** `POST /v1/apps/openmates/skills/share-usecase` — requires API key auth, rate-limited to 30 req/min. No `GET` endpoint is registered (`api_config.expose_get: false` in `app.yml`).

---

### 5. Normal Focus Mode Activation (non-onboarding)

When the AI preprocessor selects the `welcome` focus mode outside of the pre-activated onboarding chat (e.g., a user types `@focus:openmates:welcome`), the standard activation flow applies:

1. AI calls the `activate_focus_mode` tool
2. `main_processor.py` stores a pending context in Redis and schedules `focus_mode_auto_confirm_task` with a 5-second countdown
3. Client receives a `focus_mode_activated` event embed and shows a 4-second countdown (`FocusModeActivationEmbed`)
4. If not rejected, the Celery task publishes `focus_mode_activated` to Redis, which is forwarded over WebSocket to the client
5. Client encrypts the focus ID and writes `encrypted_active_focus_id` to IndexedDB, then sends `update_encrypted_active_focus_id` back to the server for persistence

See [Focus Mode Architecture](web_app.md) for the full generic focus mode flow.

---

## Data Flow Summary

```
User consents to share
         │
         ▼
ShareUsecaseSkill.execute(summary, language, user_id=<ignored>)
         │
         ├─► directus_service.create_item("onboarding_usecases", {
         │       summary, language, timestamp
         │   })
         │
         └─► celery.send_task("send_usecase_submitted_notification", {
                 admin_email: SERVER_OWNER_EMAIL,
                 summary,
                 language
             }, queue="email")
                  │
                  ▼
         EmailTemplateService.send_email(
             template="usecase_submitted",
             recipient=admin_email,
             context={ summary (HTML-escaped), language }
         )
```

---

## Environment Variables

| Variable             | Used By                  | Description                                       |
| -------------------- | ------------------------ | ------------------------------------------------- |
| `SERVER_OWNER_EMAIL` | `share_usecase_skill.py` | Admin email for use-case submission notifications |

---

## Related Documentation

- [Web App Architecture](web_app.md)
- [Signup/Login Flow](signup_login.md)
- [Focus Mode Architecture](web_app.md)
