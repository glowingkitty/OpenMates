---
status: active
last_verified: 2026-06-04
key_files:
- frontend/packages/ui/src/tokens/sources/colors.yml
- frontend/packages/ui/src/tokens/generated/theme.generated.css
claims:
- id: arch-colors-behavior
  type: unit
  claim: Color Tokens is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/packages/ui/src/tokens/sources/colors.yml
  - frontend/packages/ui/src/tokens/generated/theme.generated.css
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-colors-behavior
  verified: '2026-06-11'
- id: arch-colors-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-colors-source-1
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/tokens/generated/theme.generated.css
- id: arch-colors-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-colors-source-2
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/tokens/sources/colors.yml
- id: arch-colors-manual-3
  type: manual
  reason: 'Tiny architecture note: source-file existence claims cover the implemented anchor surface; deeper behavior remains
    covered by linked canonical docs.'
---

# Color Tokens

Color tokens are authored in `frontend/packages/ui/src/tokens/sources/colors.yml` and generated into CSS, TypeScript, Swift tokens, and Apple asset catalogs by `npm run build:tokens` in `frontend/packages/ui`.

Text color tokens used on light backgrounds must meet WCAG AA contrast for normal text unless a component documents a larger-text-only use. The deterministic accessibility audit checks generated light-theme font tokens against a 4.5:1 threshold.

Generated token outputs are ignored in this repo. Commit source token changes and rely on the token build step to regenerate platform outputs.
