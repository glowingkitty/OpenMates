# Landing native screenshot handoff

The desktop assets were captured from the deployed `app.dev.openmates.org` app on 2026-10-15. Their visible browser chrome intentionally says `openmates.org`; `capture-manifest.json` records the actual development origin and deployed revision. Chat captures start at the top. The mobile assets currently remain mobile-web captures.

For the Mac/Apple chat, create genuine iPhone simulator captures for these landing sections. Use the personal development test account, keep unrelated private content and identity out of the image, close the sidebar, and preserve the actual native UI. Do not override OpenMates' automatic model routing.

| Section | Required native view | Destination / asset stem |
| --- | --- | --- |
| Actionable chats | AI events example, top of chat with successful results visible | `example-ai-workshops-meetups-berlin` — `events-mobile.webp` |
| Privacy | New unsent fictional draft showing detected email and phone highlighting | `privacy-mobile.webp`; current related example `example-plumber-message-email-phone` |
| No ecosystem lock in | Open model selector, leave Auto select unchanged | `model-selector-mobile.webp` |
| Workflow automation | Existing Weekly Berlin AI events template in the workflow editor | Workflows workspace / `berlin-ai-events` — `workflows-mobile.webp` |
| Consistent experience | Same train example at the top on iPhone and Apple Watch | `example-deutschlandticket-train-fare-breakdown` — `devices-mobile.webp` and `devices-watch.webp` |

Verify the events example ID against `landingSectionExamples.actionable` before capture; canonical app metadata may change that selection. The workflow screenshot currently links to the existing Workflows workspace because a new real generated candidate failed admission (invalid embed link and omitted requested search-date bounds). Do not publish that candidate as an example.

Export image pixels without simulator window chrome or a second decorative device frame. Keep full resolution; review legibility and safe crop before replacing assets. Put reviewed assets in **both** `frontend/apps/website/static/landing/screenshots/` and `frontend/apps/web_app/static/landing/screenshots/`, and update provenance manifests. Do not label mobile-web images as native.

The phone SVG aperture has ratio `1170 / 2532`; the image is clipped to its rounded opening. Check the native capture's crop in the actual landing section. `DeviceScreenshots` already supports a real optional Watch capture over the bottom-left of the phone. Once the Watch image is reviewed and present in both static folders, set `landingDeviceMedia.devicesWatch` in `landingPageContent.ts` to `/landing/screenshots/devices-watch.webp`. Until then it is intentionally absent. No fabricated Watch UI is used.
