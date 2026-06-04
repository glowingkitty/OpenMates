---
name: create-newsletter
description: Draft a newsletter campaign in openmates-marketing from release notes, product notes, or a brief; creates meta.yml plus EN/DE markdown and validates the campaign before preview/scheduling
user-invocable: true
argument-hint: "<slug-or-topic> [--mode email_only|public_page]"
---

## Overview

Creates a newsletter campaign under `openmates-marketing/campaigns/<folder>/`.

This skill is for drafting campaign source only. It does **not** send a real
broadcast. After drafting, hand off to:

- `publish-newsletter` for the legacy public-page flow that commits demo-chat files.
- The newsletter campaign admin API / future `schedule-newsletter` skill for Directus-backed scheduling.

## Source Files

Each campaign folder must contain:

```text
meta.yml
newsletter_EN.md
newsletter_DE.md
```

Use existing campaigns as examples:

```bash
ls /home/superdev/projects/openmates-marketing/campaigns/
```

## Required Questions

Before drafting, ask for any missing essentials:

- Campaign focus and audience.
- Newsletter mode: `email_only` or `public_page`.
- Category: `updates_and_announcements`, `tips_and_tricks`, or another explicit category.
- CTA URL and CTA text.
- Source notes: release notes, product changes, video link, example chat URL, or brief.
- Desired send date/time if the user wants scheduling after approval.

## Drafting Rules

- Create content in `openmates-marketing`, not `OpenMates`.
- Do not create or edit MJML per campaign. The reusable MJML template lives at
  `OpenMates/backend/core/api/templates/email/newsletter.mjml`.
- Campaigns provide metadata and markdown only; OpenMates owns the email layout,
  footer, unsubscribe links, branding, and compliance.
- `title` frontmatter must not contain `OpenMates`; the subject may contain it.
- Keep the newsletter user-facing. Avoid internal debugging, tests, architecture,
  or implementation details unless the user explicitly asks.
- Mention stability/performance only briefly and concretely.
- Use `[cta]` exactly where the main call-to-action button should appear.
- Use `[video]` only when `meta.yml` contains video metadata.
- EN and DE should have the same structure, markers, headings, and CTAs.

## `meta.yml` Shape

```yaml
slug: short-kebab-case-slug
mode: email_only
category: updates_and_announcements
cta_url: https://openmates.org
cta_text:
  en: Open OpenMates
  de: OpenMates öffnen
show_social_media: false
```

For public-page campaigns add one of:

```yaml
chat_id: announcements-short-kebab-case-slug
public_page_url: https://openmates.org/#chat-id=announcements-short-kebab-case-slug
```

## Markdown Frontmatter

Each `newsletter_<LANG>.md` must start with:

```markdown
---
subject: "OpenMates ..."
title: "Visible title without brand prefix"
subtitle: Optional subtitle
cta_text: Open OpenMates
---
```

## Validation Checklist

Before reporting completion:

```bash
grep -n "\[cta\]\|\[video\]\|subject:\|title:\|cta_text:" \
  /home/superdev/projects/openmates-marketing/campaigns/<folder>/newsletter_EN.md \
  /home/superdev/projects/openmates-marketing/campaigns/<folder>/newsletter_DE.md
```

Check:

- Same `[cta]` / `[video]` marker placement in EN and DE.
- `meta.yml` slug matches the folder intent and is lowercase kebab-case.
- `category` matches the subscriber audience.
- `title` avoids `OpenMates` brand prefix.
- CTA URL is intentional and production-safe.

## Approval Gate

Never send the real newsletter from this skill.

The required production flow is:

1. Draft campaign.
2. Send admin preview/test email.
3. User confirms the email design and links.
4. Only then approve and schedule/send through the admin campaign API.
