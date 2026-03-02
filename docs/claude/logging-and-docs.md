# Logging and Documentation Standards

Load this document when adding logging, error handling, or updating documentation.

---

## Logging and Error Handling

### Backend (Python)

- **Use `logging`**: Always use `logger.debug()` or `logger.info()` instead of `print()`
- **Initialization**: Use `logger = logging.getLogger(__name__)` at the module level
- **No Silent Failures**: Never use silent fallbacks. Log errors or raise exceptions.

### Frontend (Svelte/TypeScript)

- **Use `console.log()`**: Preferred for debugging
- **Error visibility**: Ensure errors are visible in the console

### Correlation IDs

**Always include in logs:**

```python
logger.info(f"[Task ID: {task_id}] Processing message {message_id} for chat {chat_id}")
logger.error(f"Error in task {task_id}: {e}", exc_info=True)
```

### Structured Logging Prefixes

- `[PERF]` - Timing
- `[TASK]` - Celery tasks
- `[SYNC]` - Sync operations
- `[CACHE]` - Cache operations
- `[ERROR]` - Errors

### Guidelines

- **Keep Logs**: Only remove debugging logs after the user confirms the issue is fixed
- **Comments**: Add extensive comments explaining complex logic and architectural choices
- **Cache First**: Update server cache BEFORE Directus/disk to ensure data consistency

---

## Documentation Standards

### Document Structure

Every documentation file MUST include:

1. **Title** (H1) - Clear, descriptive title
2. **Status Badge** - Implementation status
3. **Last Updated** - Date of last significant update
4. **Overview** - Brief description of what the document covers

```markdown
# Feature Name

> **Status**: ✅ Implemented | ❌ Not Yet Implemented  
> **Last Updated**: 2024-10-01

Brief overview of what this document describes.
```

### Code-Documentation Synchronization

#### When Modifying Code

When modifying functions, classes, or modules that are referenced in architecture docs:

1. **Search for references**: `rg "filename.ts" docs/architecture/`
2. **Update any stale references**: If you renamed, moved, or deleted the referenced code
3. **Update doc descriptions**: If the behavior changed significantly

#### Documentation Reference Format

Use relative paths with function/class anchors (NOT line numbers, NO copy & pasted code blocks):

- ✅ `[cryptoService.ts#decryptChatData()](../../frontend/packages/ui/src/services/cryptoService.ts)`
- ❌ `cryptoService.ts:200-250` (line numbers become stale)

#### Critical Architecture Docs to Keep in Sync

- `docs/architecture/sync.md` → Sync and encryption flows
- `docs/architecture/message-processing.md` → AI message handling
- `docs/architecture/payment-processing.md` → Billing flows

### DRY Principle for Documentation

**Link Instead of Repeating:**

```markdown
<!-- ❌ BAD: Repeating details -->

## How Messages Are Processed

The message processing system uses a multi-phase approach...

<!-- ✅ GOOD: Link to canonical source -->

## Message Processing

For details, see [Message Processing Architecture](../architecture/message-processing.md)
```

### Navigation

Every document MUST end with "Read Next" links to related documentation.

---

## Key Files by Domain

### Authentication & Security

- Login flow: `backend/core/api/app/routes/auth_routes/auth_login.py`
- Crypto service: `frontend/packages/ui/src/services/cryptoService.ts`
- Key storage: `frontend/packages/ui/src/services/cryptoKeyStorage.ts`

### Chat & Sync

- Sync architecture: `docs/architecture/sync.md`
- Phased sync service: `frontend/packages/ui/src/services/PhasedSyncService.ts`
- Cache warming: `backend/core/api/app/tasks/user_cache_tasks.py`
- WebSocket handlers: `backend/core/api/app/routes/websockets.py`

### AI Processing

- Message processing: `backend/core/api/app/services/message_processor.py`
- AI handlers: `backend/apps/ai/handlers/`
- AI app config: `backend/apps/ai/config.yml`

### Payments & Usage

- Payment processing: `backend/core/api/app/services/payment_service.py`
- Usage tracking: `backend/core/api/app/services/usage_service.py`

### Frontend Components

- Chat components: `frontend/packages/ui/src/components/chats/`
- Message components: `frontend/packages/ui/src/components/messages/`
- App store: `frontend/packages/ui/src/components/apps/`
