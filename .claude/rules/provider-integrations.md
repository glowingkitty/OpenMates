---
paths:
  - "backend/apps/**"
  - "backend/shared/providers/**"
  - "docs/contributing/guides/add-api.md"
---
# Provider data integrations

Provider-specific data integrations must use provider-supported documented APIs,
explicitly licensed open-data feeds, or written authorization covering the
intended access and downstream use. Published official API terms or a feed
licence suffice when they permit that use. Record the permission source and
respect its commercial-use, display, retention, attribution and rate-limit
conditions.

Never substitute undocumented website/mobile endpoints, platform-specific
scraping, access-control evasion, or an intermediary without source-use rights.
Browser automation, low volume and silence in terms do not establish permission.
If no permitted route exists, report the capability gap instead of building a
fallback. Contact providers only when the user instructs it.

General on-demand web reading is separate: fetch public pages with an identified
reader, honor robots.txt, and stop at access denials, login/paywall or CAPTCHA.
No proxy, impersonation or bypass retry. Preserve extracted text in existing
encrypted saved embeds. Crawler access is not a content licence.

New third-party providers also need the privacy updates in `.claude/rules/privacy.md`.
Full guide: `docs/contributing/guides/add-api.md`.
