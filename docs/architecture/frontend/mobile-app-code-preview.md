---
status: planned
last_verified: 2026-04-14
key_files: []
---

# Mobile App Code Preview

> Planned feature: live preview of mobile app code in the OpenMates workspace, analogous to the existing web app preview.

## Problem

Web app code already has an in-workspace preview (rendered in an iframe). Mobile app code has no equivalent — developers must build and deploy to a device or simulator manually outside of OpenMates.

## Approaches Under Consideration

### Option A: React Native + Expo (Replit's approach)

Scaffold mobile apps using React Native + Expo instead of native Swift/SwiftUI. This unlocks two preview paths:

- **In-workspace preview:** React Native Web compilation target renders the app in a phone-shaped iframe in the browser. Zero simulator infrastructure needed.
- **Real device preview:** Expo Go on the developer's physical iPhone/Android scans a QR code and runs the native build via Metro bundler. No Apps submission required for testing.
- **Apps distribution:** EAS Build (Expo's cloud build service) produces the native binary — no local Mac/Xcode required.

**Tradeoffs:**
- Preview is a web render, not a real simulator — native-only APIs (haptics, platform-specific styling, ARKit, etc.) won't appear in the browser preview
- Constrains the tech stack to React Native; no support for native Swift/SwiftUI or Flutter
- Well-proven approach: Replit uses this exact model

### Option B: Appetize.io (real simulator streaming)

Embed an [Appetize.io](https://appetize.io/product) session in the workspace. Appetize runs actual Xcode iOS Simulators in the cloud and streams them to the browser via an iframe or JavaScript SDK.

- Full iOS simulator fidelity — native APIs, platform-specific rendering, exact device behavior
- JS SDK supports `tap()`, `swipe()`, `screenshot()`, element targeting — useful for automated testing in the workspace
- Works with any iOS app (Swift, React Native, Flutter, etc.) — just upload an IPA

**Tradeoffs:**
- Requires building an IPA first (needs a Mac with Xcode, or a CI service) before the simulator can run it — adds latency to the preview loop
- More expensive than the React Native web-render approach for high-frequency previews
- Best suited as a "test on real simulator" step rather than a live-as-you-type preview

## Recommendation

For a **live-as-you-type** preview loop, Option A (React Native + Expo web render) is simpler and cheaper. For **high-fidelity simulator testing** of native apps, Option B (Appetize) is the right tool. These are complementary, not mutually exclusive.

A practical split:
- Default scaffold: React Native + Expo → instant web preview in workspace
- "Preview on simulator" button: upload IPA to Appetize, embed the streamed session

## Related Docs

- [Native Apps Architecture](./native-apps.md) — OpenMates' own native Swift/SwiftUI app plan
- [Web App](./web-app.md) — existing web preview implementation
