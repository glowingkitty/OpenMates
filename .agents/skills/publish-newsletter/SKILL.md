---
name: publish-newsletter
description: Publish a newsletter issue from openmates-marketing into the web app and optionally send a test email — runs publish_newsletter.py, rebuilds translations, deploys, then optionally test-sends
user-invocable: true
argument-hint: "<campaign-folder-name> [--test-to <email>]"
---

## Overview

Takes a campaign folder from `openmates-marketing/campaigns/` and:
1. Runs `publish_newsletter.py` to generate/update the manifest, demo chat TS, and i18n YAML
2. Rebuilds translations
3. Deploys via `sessions.py deploy`
4. Optionally sends a test email via `send_newsletter.py --test-to`

The marketing repo is mounted at `/openmates-marketing` inside the `api` container.

## Input

The user provides a campaign folder name (under `openmates-marketing/campaigns/`) and optionally a test email:

```
/publish-newsletter newsletter_update_april_15_2026
/publish-newsletter newsletter_update_april_15_2026 --test-to testing@openmates.org
```

Or the user may just describe which newsletter to publish — infer the folder name from
`ls /home/superdev/projects/openmates-marketing/campaigns/`.

## Steps

### Newsletter Content Rules

Follow these rules before publishing or sending a test email:

- The email/content header `title` in frontmatter must not contain `OpenMates`. `OpenMates` is fine in the `subject` and body text, but not in visible headings such as `OpenMates v0.11: ...` because it can cause email header formatting issues. Prefer `v0.11: Code tools, daily inspirations & new media providers`.
- Announcements must emphasize useful features and practical daily-life/work use cases. Avoid centering the announcement around debugging, test fixes, or generic stability work.
- Stability and performance work may be mentioned only briefly, using a short sentence like `Improved stability and performance in chat sync, embeds, and file previews.` Do not list debugging, E2E, or internal implementation details.
- Do not duplicate standalone announcements. If a feature such as referrals has its own announcement/newsletter, remove it from the release announcement except for a very short cross-reference if the user explicitly asks.
- Avoid vague headings such as `More creative media tools`. Name the actual user-facing additions: new models, new providers, new generation modes, new supported media types, or concrete workflows.
- Do not call design-only changes new features. For example, if follow-up suggestions already existed and only the design changed, describe it as a design/presentation improvement or omit it.
- Remove unclear claims such as `improved Stripe checkout` unless the user-facing change is specific and verifiable.
- Announcement web-app posts should show `Published ...`, not `Started ...`, including older generated posts such as v0.9.

### 1. Resolve campaign folder

List available campaigns and confirm the target folder:

```bash
ls /home/superdev/projects/openmates-marketing/campaigns/
```

Read `meta.yml` in the campaign folder to confirm the slug, category, and video config:

```bash
cat /home/superdev/projects/openmates-marketing/campaigns/<folder>/meta.yml
```

### 2. Check both language files are consistent

Before publishing, verify EN and DE have the same structural changes (same social links,
same sections, matching `[video]` and `[cta]` markers):

```bash
grep -n "YouTube\|video\|\[cta\]" \
  /home/superdev/projects/openmates-marketing/campaigns/<folder>/newsletter_EN.md \
  /home/superdev/projects/openmates-marketing/campaigns/<folder>/newsletter_DE.md
```

Flag any mismatch to the user before continuing.

### 3. Publish (generate repo files)

```bash
docker exec api python /app/backend/scripts/publish_newsletter.py \
    --issue-dir /openmates-marketing/campaigns/<folder>/
```

This writes/overwrites:
- `backend/newsletters/issues/<slug>.yml` — email manifest
- `frontend/packages/ui/src/demo_chats/data/<kind>_<snake_slug>.ts` — demo chat
- `frontend/packages/ui/src/i18n/sources/demo_chats/<kind>_<snake_slug>.yml` — i18n source
- Patches `newsletterChatStore.ts` (import + registration)

### 4. Rebuild translations

```bash
cd frontend/packages/ui && npm run build:translations
```

### 5. Deploy

Start a session if one isn't already active:

```bash
python3 scripts/sessions.py start --mode feature --task "publish newsletter: <slug>"
```

Track and deploy the changed files:

```bash
python3 scripts/sessions.py deploy --session <SESSION_ID> \
    --title "feat(newsletter): publish <slug>" \
    --message "Re-publish <slug> with updated content from openmates-marketing." \
    --end
```

### 6. Send test email (if requested)

```bash
docker exec -i api python /app/backend/scripts/send_newsletter.py \
    --slug <slug> \
    --test-to <email> \
    --lang en
```

Confirm "Test send: OK" in the output. Report the landing page URL from the script output.

## Key files

| File | Purpose |
|------|---------|
| `openmates-marketing/campaigns/<folder>/meta.yml` | Slug, category, video config, CTA |
| `openmates-marketing/campaigns/<folder>/newsletter_EN.md` | EN body (frontmatter: title/subject, subtitle, cta_text) |
| `openmates-marketing/campaigns/<folder>/newsletter_DE.md` | DE body |
| `backend/newsletters/issues/<slug>.yml` | Generated email manifest (read by send_newsletter.py) |
| `backend/scripts/publish_newsletter.py` | Publisher — reads marketing MD, writes repo files |
| `backend/scripts/send_newsletter.py` | Dispatcher — reads manifest, sends via Brevo |
| `frontend/packages/ui/src/demo_chats/data/` | Generated demo chat TS |
| `frontend/packages/ui/src/i18n/sources/demo_chats/` | Generated i18n YAML source |

## Language notes

- `SUPPORTED_LANGS = ("en", "de")` — only EN and DE bodies are authored
- All other languages (FR, ES, ZH, …) fall back to EN at send time
- The i18n YAML contains stubs for 21 languages; untranslated locales also fall back to EN

## Sending the real broadcast

This skill only handles publishing + test sends. The actual broadcast is a separate,
destructive, irreversible action — run it manually:

```bash
docker exec -it api python /app/backend/scripts/send_newsletter.py \
    --slug <slug> \
    --send
```

The script requires an interactive TTY (`-it`) and prompts for explicit confirmation
before sending. `sent_at` in the manifest is set after a successful broadcast;
a second run requires `--resend-confirm`.
