---
description: Privacy policy update checklist for new third-party providers
globs:
  - "**/privacy*"
  - "**/legal*"
  - "shared/docs/privacy_policy.yml"
  - "frontend/packages/ui/src/i18n/sources/legal/**"
---

## Privacy Policy Updates

When adding a new third-party provider, update ALL of these:
1. `shared/docs/privacy_policy.yml`
2. `i18n/sources/legal/privacy.yml`
3. `legal/buildLegalContent.ts`
4. `config/links.ts`
5. Update `lastUpdated` in `privacy-policy.ts`

## MANDATORY: Verify Privacy Policy URLs Before Saving

**NEVER save a privacy policy URL without verifying it first.** URL schemas change frequently and many providers move their policies without redirects.

Before adding or updating any `privacy_policy:` URL in `privacy_policy.yml` or `links.ts`:

1. **Verify the URL using firecrawl** — check the status code is 200 and the page title confirms it is the privacy policy:
   ```
   mcp__firecrawl__firecrawl_scrape(url, formats=["json"], jsonOptions={"prompt": "Status code and page title — is this a valid privacy policy?"})
   ```

2. **If 404 or wrong page** — search for the correct URL:
   - Try common patterns: `/privacy`, `/legal/privacy`, `/legal#privacy-policy`, `legal.{domain}/terms/privacy-policy`
   - Or use `mcp__firecrawl__firecrawl_scrape` on the provider's homepage/legal page and follow links

3. **Add a verification date comment** when the URL is not at an obvious canonical path:
   ```yaml
   privacy_policy: https://legal.mistral.ai/terms/privacy-policy  # verified 2026-04-14
   ```

**Known non-obvious URLs (verified 2026-04-14):**
- Mistral: `https://legal.mistral.ai/terms/privacy-policy` (not mistral.ai/privacy-policy)
- fal.ai: `https://fal.ai/legal/privacy-policy` (not fal.ai/privacy-policy)
- Recraft: `https://www.recraft.ai/privacy` (not recraft.ai/privacy-policy)
- SerpApi: `https://serpapi.com/legal#privacy-policy` (embedded in terms page)
- Revolut Business: `https://www.revolut.com/en-LT/legal/privacy/` (Lithuania entity)
