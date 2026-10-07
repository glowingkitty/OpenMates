---
status: active
last_verified: 2026-06-15
key_files:
- frontend/apps/web_app/src/routes/+layout.svelte
- frontend/apps/web_app/src/routes/+page.svelte
- frontend/packages/ui/src/legal/documents/privacy-policy.ts
- frontend/packages/ui/src/legal/documents/terms-of-use.ts
- frontend/packages/ui/src/legal/documents/imprint.ts
- frontend/packages/ui/src/services/websocketService.ts
- frontend/packages/ui/src/stores/authLoginLogoutActions.ts
claims:
- id: arch-frontend-web-app-behavior
  type: unit
  claim: Web App Architecture is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/apps/web_app/src/routes/+layout.svelte
  - frontend/apps/web_app/src/routes/+page.svelte
  - frontend/packages/ui/src/legal/documents/privacy-policy.ts
  - frontend/packages/ui/src/legal/documents/terms-of-use.ts
  - frontend/packages/ui/src/legal/documents/imprint.ts
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-frontend-web-app-behavior
  verified: '2026-06-11'
- id: arch-frontend-web-app-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-web-app-source-1
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/+layout.svelte
- id: arch-frontend-web-app-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-web-app-source-2
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/+page.svelte
- id: arch-frontend-web-app-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-web-app-source-3
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/legal/documents/imprint.ts
---

# Web App Architecture

> The OpenMates web app at `openmates.org` serves as both the product landing page and the full application, replacing the old informative website.

## Why This Exists

A single web app reduces development effort and gives visitors immediate exposure to product capabilities. Unauthenticated visitors see demo chats that showcase features; authenticated users get the full experience.

## How It Works

### Temporary marketing landing page

`/landing` is a server-rendered public route under `(marketing)`, with a reset
layout that reuses the app's fonts, colors and icons without starting account
synchronization. Its full-height hero keeps the app rails and rotating prompts;
visitors scroll the feature sections while the composer link stays fixed to the
viewport. `/#compose` focuses the real app editor and preserves a guest draft.
App and website destinations are independently configurable for the later
[website/app domain split](../web-app-landing-domain-split.md).

### Connection and sync feedback

`ConnectionStatusController.svelte` feeds browser connectivity, authenticated
WebSocket status and `chatSyncActivityStore.ts` into `connectionFeedbackStore.ts`.
`Settings.svelte` renders the transient Wi-Fi/sync slot beside the fixed profile;
`Header.svelte` adjusts the compact workspace selector when that slot is visible.
Browser/device offline status shows a static airplane for all users. Signed-out
users never show animated Wi-Fi or sync feedback and reserve no space online.
Idle collapses the slot and moves the neighboring controls back over 200ms.
The controller preserves the 3s socket-loss delay, 10s wake grace and 12s stuck
auth-check detection. Sync appears only after 600ms of an actual phased sync
request and ends on a matching full server completion or an interruption.
Offline-change replay contributes independent activity until its acknowledgement,
send failure, disconnect or 30s timeout; completing one sync keeps the other visible.
Cached/synthetic UI-readiness completions and ordinary incoming messages do not
start sync activity. Routine connection/reconnected/cache-recovery notifications
and offline-replay progress/success cards are replaced by this slot; actionable
sync errors and conflicts remain in the notification deck.

### Unauthenticated Experience

When a visitor loads `openmates.org` without being logged in:

1. The main surface opens on the **new-chat welcome screen** rather than auto-opening a demo chat.
2. **Demo chats** remain available in the sidebar and from welcome cards with fixed chat IDs (for deep-linkable URLs like `/chat/stay-up-to-date-contribute`). These are precompiled into the static bundle for SEO and fast load times.
3. **Legal chats** (Privacy Policy, Terms of Use, Imprint) are always shown alongside demo chats using the same static-bundle infrastructure.
4. Logged-out visitors see OpenMates product explainer daily inspirations and a local interest tag rail. Selected guest tags are stored only in `sessionStorage` under `openmates.guest_interest_tags.v1` and locally reorder inspirations, demo/example chats, and new-chat suggestions.
5. The message input shows a **"Signup to send"** button instead of "Send", which opens the signup flow and saves the draft message.

### Topic Preferences

Guest topic preferences are privacy-preserving by default. Before signup, cleartext selected tags never leave the browser session and are not written to `localStorage`.

After login or signup, the web client promotes selected guest tags into encrypted account settings. The API route `POST /v1/settings/topic-preferences` accepts only encrypted settings ciphertext, and the server does not inspect selected tag IDs. Authenticated web, CLI, and Apple clients decrypt the topic preference payload locally to display Settings > Account > Interests and to rank public fallback surfaces when the account has no personal chats yet.

### Demo Chat Content

- "Welcome to OpenMates!" -- short product introduction
- "What makes OpenMates different?" -- comparison to ChatGPT, Claude, etc.
- Monthly changelog summary
- Example chats: learning, app power, personalization
- "OpenMates for developers" -- developer features + Signal group link
- "Stay up to date & contribute" -- social media and community links

### Legal Document Infrastructure

Legal documents are stored as TypeScript files in `frontend/packages/ui/src/legal/documents/`:
- `privacy-policy.ts`
- `terms-of-use.ts`
- `imprint.ts`

**Updating legal documents requires three steps:**
1. Update the static legal chat files for new users
2. Send follow-up messages to existing users with a summary of changes
3. Include the updated full text as an assistant message

### Post-Signup Flow

On signup completion, demo chats are kept and the user receives a message explaining they can delete the example chats. Draft messages saved before signup are sent automatically.

### WebSocket Auth Expiry

`websocketService.ts` dispatches an `authError` event when the server rejects the WebSocket with an authentication or policy-violation signal. The app shell handles that event in `+page.svelte` by running the local logout cleanup directly instead of re-checking `/auth/session`, because the session check intentionally treats non-OK responses as offline-first recoverable failures. Pair-login deep links are explicitly excluded so stale WebSocket failures from an old session do not invalidate a fresh passkey pairing flow.

### Recent Workspace Navigation

Task, Plan, and Project services retain bounded query and entity results across page mounts through `workspaceQueryCache.ts`. Keys include the account, API environment, team, and key epoch. Loaded empty results count as cached data. Identical requests share one pending read; warm results render immediately while stale results refresh in the background. Local mutations update the shared results, and generations prevent earlier reads from replacing newer changes or repopulating a cleared identity. Logout and key/team changes clear these decrypted memory caches. Visible views also refresh on focus, reconnect, and their existing polling schedule.

Task detail uses the selected `/v1/user-tasks/{id}` record and its owner assignment metadata. Linked context resolves cached entities or explicit related IDs independently of the main content. Opening one Task does not fetch the full Task, Plan, or Project list. Task board moves serialize each Task's action and reorder, and late action results cannot restore a previous account's board.

`recentChatWindowCache.ts` retains up to eight settled persisted message windows within a 16 MiB payload budget. A matching authenticated selection can seed `ActiveChat` on its first render or publish an in-place selection before the route metadata and canonical IndexedDB reads finish. The composer waits for canonical ownership and draft context; cached history remains visible during that wait. Message mutations invalidate the snapshot and let a pending read retry; account, team, or key revocation clears the early plaintext and rejects its old completion. Public, anonymous, incognito, draft-only, and streaming content do not enter this recent-window path. Existing encrypted IndexedDB chat storage remains canonical; these additional decrypted projections stay in memory.

Workflows use the existing workspace store. Detail publication proceeds independently of run history, and background refresh preserves dirty editor state. A clean editor adopts refreshed graphs, including after a pending node draft closes. An unknown deep link verifies the list before treating the Workflow as missing, even when the cached list is empty. Native hash events and SvelteKit URL updates both keep the root workspace selection current. See the [navigation cache Plan](../../plans/web-workspace-navigation-cache/plan.yml) for scope and verification evidence.

### Onboarding

See [Onboarding Guide](../../user-guide/onboarding.md) for the implemented user onboarding flow.

## Native Apps

The web app is the primary client and ships new features first. Fully
native Apple clients (iPhone, iPad, Mac, Apple Watch) are planned and
tracked separately in [Native Apps Architecture](./native-apps.md).

## Related Docs

- [Native Apps](./native-apps.md) -- Apple-first native app strategy
- [Accessibility](./accessibility.md) -- WCAG compliance patterns
- [Daily Inspiration](./daily-inspiration.md) -- content generation pipeline
- [Docs Web App](./docs-web-app.md) -- documentation rendering at `/docs`
- [Frontend Dependency Pins](../audit_frontend_dependency_pins.md) -- lockfile guard for editor and asset-loading regressions
