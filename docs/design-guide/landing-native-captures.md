# Landing native screenshot handoff

The desktop assets were captured from the deployed `app.dev.openmates.org` app on 2026-10-15. Their visible browser chrome intentionally says `openmates.org`; `capture-manifest.json` records the actual development origin and deployed revision. Chat captures start at the top. The mobile assets currently remain mobile-web captures.

For the Mac/Apple chat, create genuine iPhone simulator captures for these landing sections. Use the personal development test account, keep unrelated private content and identity out of the image, close the sidebar, and preserve the actual native UI. Do not override OpenMates' automatic model routing.

| Section | Required native view | Destination / asset stem |
| --- | --- | --- |
| Privacy | New unsent fictional draft showing detected email and phone highlighting | `privacy-mobile.webp` |
| No ecosystem lock in | Open model selector, leave Auto select unchanged | `model-selector-mobile.webp` |
| Workflow automation | Existing Weekly Berlin AI events template in the workflow editor | Workflows workspace / `berlin-ai-events` — `workflows-mobile.webp` |

Capture only admitted examples from the current public registry. Sections without an admitted demonstration keep screenshots and chat links absent. The workflow screenshot links to the existing Workflows workspace; it is not a published example chat.

Export image pixels without simulator window chrome or a second decorative device frame. Keep full resolution; review legibility and safe crop before replacing assets. Put reviewed assets in **both** `frontend/apps/website/static/landing/screenshots/` and `frontend/apps/web_app/static/landing/screenshots/`, and update provenance manifests. Do not label mobile-web images as native.

The phone SVG aperture has ratio `1170 / 2532`; the image is clipped to its rounded opening. Check the native capture's crop in the actual landing section. `DeviceScreenshots` supports a real optional Watch capture over the bottom-left of the phone. Publishing one requires a reviewed genuine native capture and an admitted demonstration. No fabricated Watch UI is used.
