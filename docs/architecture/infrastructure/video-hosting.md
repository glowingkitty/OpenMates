---
status: active
decided: 2026-04-14
decision: Bunny Stream (PAYG)
review_task: OPE-426
---

# Video Hosting

Provider decision for self-hosted product demo videos (not YouTube).

## Decision

**Bunny Stream** — pay-as-you-go, EU-native.

Chosen over api.video because api.video requires a €49/month minimum commitment.
At our current scale (handful of demo videos, low delivery volume), true PAYG is required.

See OPE-426 for when to re-evaluate api.video.

## Provider Comparison

Researched April 2026. All providers evaluated for: EU data residency, GDPR/DPA, embed
tracking, pricing, developer experience, reliability, and player customization.

| Provider | HQ | EU Data Residency | Embed Tracking | Storage | Delivery | Notes |
|---|---|---|---|---|---|---|
| **Bunny Stream** ✓ | Slovenia (EU) | Native | None (anon perf metrics) | $0.01/GB/mo | $0.005/GB | PAYG, no minimum |
| **api.video** | France (EU, OVHcloud) | Native | None (in-platform analytics) | ~$0.19/GB/mo | $0.0017/min | €49/mo minimum |
| **PeerTube** | Self-hosted | 100% yours | Zero | ~€20–50/mo infra | Included | Requires DevOps |
| **Cloudflare Stream** | US (EU PoPs) | No EU-only option | Bot cookies only | $5/1k mins | $1/1k mins | US company |
| **Mux** | US (EU ingest only) | Analytics only | First-party anon (disableable) | $0.0024/min | $0.0008/min | US company, best DX |
| **Vimeo** | US (EU = Enterprise only) | Enterprise only | `vuid` cookie (needs `?dnt=1`) | $12–75/mo flat | Included (2TB cap) | US company |

## Why Bunny Stream

- **EU-native** (Slovenia) — no CLOUD Act, no EU-US DPF workarounds
- **Zero viewer tracking** on embeds — anonymous performance metrics only, no cookies, no ad networks
- **Cheapest at scale** — a handful of demo videos costs cents/month
- **Full branding removal** — custom CSS, own player, or raw HLS to Video.js/Plyr
- **PAYG** — no monthly minimum, charges only for storage and delivery used
- DRM (Widevine + FairPlay) included if ever needed

## Known Risks

- Bunny Stream is less mature than Bunny CDN (their general CDN product is battle-tested; Stream is younger)
- No first-party React/Vue SDK — only iframe embed; custom player requires rolling own HLS.js
- **April 2025 incident:** Bunny Storage silently dropped uploaded files for 15 months on a production
  account, only fixed after a Reddit post went viral. Support had ignored tickets for 15 months.
  This is a Storage bug (not Stream), but reveals support culture issues. Mitigation: keep original
  video files locally, do not treat Bunny as the only copy.
- Basic aggregate-only analytics (no per-viewer QoE data)
- 2022 DNS outage (~2 hours, documented in their post-mortem)

## Mitigation

Always keep original video source files in the repo or a local backup. Bunny is the CDN/delivery
layer only — not the source of truth.

## Why NOT api.video (for now)

api.video is the stronger long-term choice (better DX, French law DPA, praised support, no known
incidents, open-source player). Blocked only by the €49/month minimum commitment.

Reconsider when: api.video offers PAYG, or Bunny spend exceeds ~€30/month, or Bunny support
issues arise. See OPE-426.

## Why NOT others

- **Cloudflare Stream / Mux / Vimeo**: US companies, no genuine EU-only data residency at
  reasonable pricing. Not appropriate for a privacy-focused product making GDPR commitments.
- **PeerTube**: Ideal for data sovereignty but requires meaningful DevOps investment. Worth
  revisiting when infra maturity justifies it.
