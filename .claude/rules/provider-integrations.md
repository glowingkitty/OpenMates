---
paths:
  - "backend/apps/**"
  - "backend/shared/providers/**"
  - "docs/contributing/guides/add-api.md"
---
# Provider data integrations

Provider-specific data integrations use only the provider's official, documented
API or an official open-data feed. Confirm the official documentation supports
the intended use, record its URL, and follow its usage, attribution and
rate-limit conditions.

Never substitute undocumented website/mobile endpoints, platform-specific
scraping, browser automation, proxies or third-party resellers of another
platform's data. If no official route exists, report the capability gap instead
of building a fallback. Contact providers only when the user instructs it.

General on-demand web reading is separate: fetch public pages with an identified
reader, honor robots.txt, and stop at access denials, login/paywall or CAPTCHA.
No proxy, impersonation or bypass retry. Preserve extracted text in existing
encrypted saved embeds. The reader never acts as a provider-specific connector.

New third-party providers also need the privacy updates in `.claude/rules/privacy.md`.
Full guide: `docs/contributing/guides/add-api.md`.
