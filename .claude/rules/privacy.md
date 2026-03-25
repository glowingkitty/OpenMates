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
