---
status: active
last_verified: 2026-03-24
---

# Documentation Structure

This guide explains how the `docs/` folder is organized and where to place new documentation files.

## Folder Overview

```
docs/
├── architecture/       # System design — how things work internally
├── cli/                # CLI command reference for end-users
├── contributing/       # Developer onboarding, guides, and coding standards
├── design-guide/       # UI/UX design principles and documentation writing guidelines
├── images/             # Centralized images, mirroring the doc folder structure
├── self-hosting/       # Setup instructions for self-hosters
└── user-guide/         # End-user documentation — how to use the product
```

## Placement Rules

Use this table to decide where a new document belongs:

| Folder | Put here when... | NOT here when... |
|--------|-----------------|-------------------|
| `architecture/` | Documenting a system's internal design, data flow, component interactions, or recording an architecture decision | It's a how-to procedure (→ `contributing/guides/`) or a coding convention (→ `contributing/standards/`) |
| `contributing/guides/` | Writing step-by-step instructions for a developer task (debugging, adding an API, deploying, implementing a new embed type) | It's a design decision (→ `architecture/`) or a rule to follow (→ `contributing/standards/`) |
| `contributing/standards/` | Defining rules, conventions, or patterns that code must follow (naming, file structure, linting, component patterns) | It's a one-off procedure (→ `contributing/guides/`) or a system explanation (→ `architecture/`) |
| `design-guide/` | Defining how the UI should look/behave, component usage guidelines, or how documentation should be written | It's about code patterns (→ `contributing/standards/`) or system internals (→ `architecture/`) |
| `user-guide/` | Explaining a feature or workflow to end-users who use the product | The audience is developers (→ `contributing/` or `architecture/`) |
| `cli/` | Documenting CLI commands and usage for end-users | It's about building or extending the CLI (→ `contributing/guides/` or `architecture/`) |
| `self-hosting/` | Providing setup, configuration, or maintenance instructions for people hosting their own instance | It's about the hosted product (→ `user-guide/`) or development (→ `contributing/`) |
| `images/` | Storing screenshots, diagrams, or other visual assets referenced by docs | Images should NOT live next to docs — always use the centralized `images/` folder |

## Quick Decision Flowchart

```
Is this for end-users?
├── Yes → user-guide/ (or cli/ for CLI commands, self-hosting/ for self-hosters)
└── No (developer audience)
    ├── Does it explain HOW a system works? → architecture/
    ├── Does it explain HOW TO DO a task? → contributing/guides/
    ├── Does it define RULES to follow? → contributing/standards/
    └── Does it define how the UI SHOULD LOOK? → design-guide/
```

## Architecture Subfolders

The `architecture/` folder is organized by domain:

| Subfolder | Scope |
|-----------|-------|
| `ai/` | AI model selection, thinking models, hallucination, follow-up suggestions |
| `apps/` | App/skill architecture, function calling, CLI package design |
| `core/` | Security, authentication, passkeys, account management |
| `data/` | Sync protocol, device sessions, translations pipeline |
| `frontend/` | Web app architecture, accessibility, daily inspiration |
| `infrastructure/` | Logging, analytics, cron jobs, file uploads, servers, health checks |
| `integrations/` | External service integrations (calendar, email, voice, media) |
| `messaging/` | Embeds, message parsing, processing pipeline, input field |
| `payments/` | Stripe, payment flows, auto top-up |
| `privacy/` | PII protection, prompt injection, data redaction, email privacy |
| `storage/` | Cold storage, embed archival |

## Planned Features

Documents describing features that are **not yet implemented** live in their relevant architecture subfolder (not in a separate `planned/` folder) and MUST include this banner immediately after the title:

```markdown
> **Status: Planned** — This feature is not yet implemented.
```

This keeps planned docs discoverable alongside implemented features while clearly marking their status.

## Images

All images live in `docs/images/`, organized to **mirror the doc folder structure**:

```
docs/images/
├── architecture/           # Images for architecture docs
│   └── messaging/          # e.g., message flow diagrams
├── contributing/           # Images for contributing docs
├── user-guide/             # Images for user guide
│   └── apps/               # App preview screenshots
│       ├── code/
│       ├── web/
│       └── ...
└── *.png / *.jpg           # Root-level images (repo README headers, etc.)
```

**Rules:**
- Always place images in the subfolder matching the doc that references them
- Use descriptive filenames: `payment-flow-diagram.png`, not `diagram1.png`
- Reference with relative paths: `../../images/architecture/messaging/flow.png`

## File Naming Conventions

- **Filenames:** Always `kebab-case.md` (e.g., `add-embed-type.md`, `payment-processing.md`)
- **Directories:** Always lowercase with hyphens (e.g., `user-guide/`, `self-hosting/`)
- **No spaces or underscores** in filenames or directory names (legacy exceptions exist but should not be copied)

## Documentation Outside `docs/`

Some documentation intentionally lives outside this folder:

| Location | Purpose |
|----------|---------|
| `CLAUDE.md` (repo root) | AI assistant session rules and project overview |
| `README.md` (repo root) | Project introduction and feature overview |
| `*/README.md` (in modules) | Module-specific documentation, kept close to the code |
| `marketing/` (repo root) | Marketing materials, pitch decks, brand assets |

Module README files should stay local to their code. Only move content to `docs/` if it's broadly useful beyond that module.
