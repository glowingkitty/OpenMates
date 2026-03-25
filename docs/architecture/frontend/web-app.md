---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/apps/web_app/src/routes/+layout.svelte
  - frontend/apps/web_app/src/routes/+page.svelte
  - frontend/packages/ui/src/legal/documents/privacy-policy.ts
  - frontend/packages/ui/src/legal/documents/terms-of-use.ts
  - frontend/packages/ui/src/legal/documents/imprint.ts
---

# Web App Architecture

> The OpenMates web app at `openmates.org` serves as both the product landing page and the full application, replacing the old informative website.

## Why This Exists

A single web app reduces development effort and gives visitors immediate exposure to product capabilities. Unauthenticated visitors see demo chats that showcase features; authenticated users get the full experience.

## How It Works

### Unauthenticated Experience

When a visitor loads `openmates.org` without being logged in:

1. **Demo chats** appear in the sidebar with fixed chat IDs (for deep-linkable URLs like `/chat/stay-up-to-date-contribute`). These are precompiled into the static bundle for SEO and fast load times.
2. **Legal chats** (Privacy Policy, Terms of Use, Imprint) are always shown alongside demo chats using the same static-bundle infrastructure.
3. The message input shows a **"Signup to send"** button instead of "Send", which opens the signup flow and saves the draft message.

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

### Onboarding

See [Onboarding Architecture](onboarding.md) for planned user onboarding features.

## Related Docs

- [Accessibility](./accessibility.md) -- WCAG compliance patterns
- [Daily Inspiration](./daily-inspiration.md) -- content generation pipeline
- [Docs Web App](./docs-web-app.md) -- documentation rendering at `/docs`
