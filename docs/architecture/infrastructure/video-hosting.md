---
status: active
decided: 2026-04-14
decision: api.video (PAYG)
---

# Video Hosting

Provider decision for self-hosted product demo videos (not YouTube).

## Decision

**api.video** — pay-as-you-go, EU-native (France / OVHcloud).

Initial research incorrectly indicated a €49/month minimum; confirmed PAYG with no minimum.

## Pricing

- Storage: $0.00285/min stored
- Delivery: $0.0017/min delivered
- Encoding: free (all resolutions)
- Free sandbox tier (30s watermarked, 24h TTL — good for dev/testing)
- Billed monthly for prior month's usage

## Why api.video

- **EU-native** (France, OVHcloud subsidiary) — DPA governed by French law/Paris courts
- **Zero viewer tracking** on embeds — in-platform aggregated analytics only, no ad networks
- **PAYG** — no monthly minimum, sandbox for free development
- **Direct HLS + MP4 URLs** — required for our custom player pattern (muted autoplay background → click → fullscreen with audio)
- **Open-source player** — fully customizable, no forced branding
- **Full SDKs** — JS, Python, Go, React/Vue components
- **Support quality** consistently praised (vs Bunny's documented support failures)
- **No known reliability incidents**

## Custom Player Pattern

We use api.video for URL delivery only — not their embedded iframe player.

Implementation for the muted-autoplay-background → fullscreen-with-audio pattern:

```html
<!-- Background: muted autoplay loop (browser allows this) -->
<video src="{hls_url}" autoplay muted loop playsinline />

<!-- On click: open fullscreen modal, unmute, play from current position -->
```

Both HLS and MP4 URLs are available per video from the api.video REST API.
Use the open-source `@api.video/player-sdk` or plain HLS.js for the fullscreen player.

## Provider Comparison (Researched April 2026)

| Provider | HQ | EU Data Residency | Embed Tracking | Storage | Delivery | Notes |
|---|---|---|---|---|---|---|
| **api.video** ✓ | France (EU, OVHcloud) | Native | None | $0.00285/min | $0.0017/min | PAYG, free sandbox, direct HLS+MP4 |
| **Bunny Stream** | Slovenia (EU) | Native | None (anon perf metrics) | $0.01/GB | $0.005/GB | PAYG, no SDK, known support issues |
| **PeerTube** | Self-hosted | 100% yours | Zero | ~€20–50/mo infra | Included | Requires DevOps — ruled out |
| **Cloudflare Stream** | US (EU PoPs) | No EU-only option | Bot cookies only | $5/1k mins | $1/1k mins | US company |
| **Mux** | US (EU ingest only) | Analytics only | First-party anon (disableable) | $0.0024/min | $0.0008/min | US company, best DX |
| **Vimeo** | US (EU = Enterprise only) | Enterprise only | `vuid` cookie (needs `?dnt=1`) | $12–75/mo flat | Included (2TB cap) | US company, iframe-only |

## Why NOT others

- **Bunny Stream**: No first-party SDK, iframe-only embed, documented April 2025 storage data loss incident + 15-month support failure. Ruled out.
- **Cloudflare Stream / Mux / Vimeo**: US companies without genuine EU-only data residency at reasonable pricing.
- **PeerTube**: Ideal for data sovereignty but requires DevOps. Not a managed SaaS.
- **Vimeo**: Iframe-only — can't implement the muted-autoplay → fullscreen-with-audio pattern cleanly.

## First Use Case

Product demo video in the `for-everyone` intro chat header (`ChatHeader.svelte`).
See `frontend/packages/ui/src/demo_chats/data/for_everyone.ts` and
`frontend/packages/ui/src/components/ChatHeader.svelte`.
