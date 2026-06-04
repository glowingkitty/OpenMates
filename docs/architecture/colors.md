---
status: active
last_verified: 2026-06-04
key_files:
  - frontend/packages/ui/src/tokens/sources/colors.yml
  - frontend/packages/ui/src/tokens/generated/theme.generated.css
---

# Color Tokens

Color tokens are authored in `frontend/packages/ui/src/tokens/sources/colors.yml` and generated into CSS, TypeScript, Swift tokens, and Apple asset catalogs by `npm run build:tokens` in `frontend/packages/ui`.

Text color tokens used on light backgrounds must meet WCAG AA contrast for normal text unless a component documents a larger-text-only use. The deterministic accessibility audit checks generated light-theme font tokens against a 4.5:1 threshold.

Generated token outputs are ignored in this repo. Commit source token changes and rely on the token build step to regenerate platform outputs.
