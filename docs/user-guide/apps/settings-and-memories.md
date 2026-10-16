---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-settings-and-memories-source
    type: unit
    claim: The Settings and Memories guide is grounded in app memory settings components.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-settings-and-memories-source
---

# Memories

> Save your preferences so your digital team mates remember them across conversations.

## What Are Memories?

Memories supply facts, preferences and useful guidance. You can save personal information within each app. For example, you can save your favourite books in the Books app, your preferred airlines in the Travel app, or your medical history in the Health app. Your mates use this information to give you more personalised help.

## How They Work

### Adding Data

There are two ways to save memories:

1. **Through conversation** -- Your mate may suggest saving something during a chat. For example, after discussing a favourite movie, it might ask "Would you like me to save this to your watched movies list?" You confirm or reject with a simple reply.

2. **Through the Apps** -- Go to Settings > Apps > select an app to view and manage its memories directly. You can add, edit, or delete entries at any time.

### App-provided and Project Memories

Apps also provide read-only Memories, such as Svelte best practices in Code or mobile first design in Design. They use the same cards as your saved memories, marked **Public** with a web icon. Your own encrypted memories are marked **Private** with a lock icon. You can inspect both in Memories or an app's details. Your mate loads relevant public app guidance automatically.

Project Memories supply context for the Project you are working on, such as its staging address or preferred libraries. Relevant Project Memories load automatically while that Project Focus is active and you have access. Leaving the Project Focus stops future loading; content already shared remains in the conversation.

A Focus mode tells your mate **how to work**, with optional phases. A Memory supplies **useful context**. A Project Specification defines **what the result must satisfy**. Imported `AGENTS.md` instructions become a Project Focus; they do not need phases.

### Permission System

Your personal memories are private and encrypted. When your mate needs access to your saved personal data during a conversation:

1. Your mate asks to see specific data (for example, your travel preferences).
2. A permission dialog appears showing exactly what data is being requested.
3. You choose which items to share or reject the request entirely.
4. Only the data you approve is used for that conversation.

This happens once per conversation and per type of private data. An explicit memory mention shares the named type or entry without another permission dialog. Personal memories about a Project still require this permission; they do not become automatically accessible Project context.

### What Gets Saved

Each app defines its own types of memories. Common examples:

- **Lists** -- Collections of items like favourite books, watched movies, or plant collections
- **Preferences** -- Single settings like your preferred writing style or communication tone

Each entry is individually encrypted in your browser before being stored, so the server holds only ciphertext on disk and in backups. When you approve an entry or mention it explicitly, your device decrypts the content and shares it transiently for that conversation — it is never written out in plain text.

## Managing Your Data

In the Apps (Settings > Apps > select an app), you can:

- **View** all saved entries organised by category
- **Add** new entries using a form
- **Edit** any existing entry
- **Delete** entries you no longer need
- **Review pending entries** that your mate suggested but you have not confirmed yet

## Multi-Device Sync

Your memories sync across all your devices. Changes on one device appear on all others automatically. If the same entry is modified on two devices, the most recent change wins.

## Tips

- You can save data proactively through the Apps settings without needing a conversation.
- Pending entries (suggested by your mate but not yet confirmed) appear in a "Pending Review" section so you can act on them later.
- Private personal and team memories require approval or an explicit mention. App-provided and accessible active Project Memories load automatically when relevant.
- All data is encrypted on your device before being stored -- the server stores only ciphertext on disk and in backups, and only decrypts transiently in memory when your mate actually needs to use it.

## Related

- [Apps](./app-store.md) -- Browse and manage apps and their settings
- [Skills](./skills.md) -- Skills can use your saved data when you give permission
- [Focus Modes](./focus-modes.md) -- Focus modes can access your data for personalised guidance
