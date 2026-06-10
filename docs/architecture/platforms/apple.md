---
status: active
doc_type: explanation
audience:
  - contributors
  - technical-users
last_verified: 2026-06-10
claims: []
---

# Apple Platform

## Summary

The Apple app is the native Swift/SwiftUI platform for iPhone, iPad, Mac, and related Apple surfaces. Web-rendered product UI remains the visual source of truth, with generated tokens and source mappings keeping native UI aligned.

## Canonical Architecture Docs

- [Native Apps Architecture](../frontend/native-apps.md) -- native app strategy and generated token pipeline.
- [Apple/Web Parity Matrix](../apple/parity-matrix.md) -- parity audit surface and source-of-truth map.
- [Design Tokens](../frontend/design-tokens.md) -- token generation shared with Apple clients.

## Source Areas

- `apple/OpenMates/` contains the Xcode project and native app sources.
- `apple/SVELTE_SWIFT_COUNTERPARTS.md` maps web source files to native counterparts.
- `frontend/packages/ui/src/tokens/generated/swift/` contains generated Swift token files referenced by Xcode.

## Related

- [Platform Architecture](README.md) -- platform index
- [Web App Platform](web-app.md) -- web source of truth
- [CLI Platform](cli.md) -- terminal client and SDK
