---
status: planned
last_verified: 2026-04-10
key_files: []
related:
  - frontend/daily-inspiration.md
  - apps/web-app.md
linear:
  - OPE-307  # related: alternative image search providers (Flickr, Wikidata)
  - OPE-24   # related: OG image generation for shared chats
---

# Chat Header Hero Images (Planned)

> Display a high-quality, topic-relevant hero image in the chat header of every new chat to add context, atmosphere, and inspiration. Bias toward historical / public-domain photography for an editorial feel.

## Status

Planned. No code yet. This document captures the research and the intended architecture so the implementation session can pick it up directly.

## Why This Exists

The current new-chat screen is visually empty until the first message arrives. A header image gives:

- **Context** — visual cue of what the chat is "about" once a topic is detected.
- **Inspiration** — historical photographs (FSA Great Depression, early NASA, museum archives) make the surface feel more like a magazine cover than a blank textarea.
- **Aesthetic uplift** — distinguishes OpenMates from competitor LLM UIs that all look like grey form fields.

This is **not** a replacement for [Daily Inspiration](./daily-inspiration.md) — daily inspiration delivers curated *video* cards before any topic is known. Hero images react to the *current chat topic* and live in the chat header.

## Source APIs (Researched 2026-04-10)

Two-tier strategy: **public-domain / GLAM** sources first (matching the historical-photo aesthetic), modern stock as fallback.

### Tier 1 — Historical / public-domain

| Provider | Content | Rate limit | Cost | License | Notes |
|---|---|---|---|---|---|
| Wikimedia Commons | ~100M+ images, huge historical archive | Unauth: 500 req/h per IP. Authed token: 5,000 req/h. Phased new limits Mar–Apr 2026. | Free | CC0 / CC BY-SA / PD | Best single source for breadth. Must send `User-Agent` with contact email. |
| Europeana | ~50M items from 3,000+ EU museums/archives | No throttle on reads; project key for higher rates | Free | Mixed; filter `reusability=open` | Strong for European history, WWI/WWII, posters, maps. Filter `qf=TYPE:IMAGE`. |
| Library of Congress | Millions of US historical photos (FSA, Civil War, P&P catalog) | Soft limits, no key | Free | Mostly PD | FSA/OWI 1930s–40s collection is gold. |
| Smithsonian Open Access | ~4.5M CC0 objects | api.data.gov default 1,000 req/h per key | Free (api.data.gov key) | CC0 | Zero-attribution license. |
| Metropolitan Museum of Art | ~500k objects, ~400k open access | 80 req/sec, no key | Free | CC0 for OA items | Art history, antiquities. |
| Rijksmuseum | ~800k artworks, prints, photos | No published hard limit; free key | Free | PD / CC0 | Dutch Golden Age, colonial-era photography. |
| NASA Image & Video Library | Space, aviation, NASA historical | Generous, no key | Free | Mostly PD | Science / space topics. |
| Flickr Commons | Curated "no known copyright" sets from institutions | 3,600 req/h | Free key | PD / "no known copyright" | Aggregates LOC, NYPL, Smithsonian. |
| DPLA | ~50M items from US libraries/museums | Free key, polite usage | Free | Mixed, filterable | Metadata aggregator. |

### Tier 2 — Modern stock (fallback)

| Provider | Free rate limit | Cost | License notes |
|---|---|---|---|
| Unsplash | 50 req/h demo → 5,000 req/h after prod approval. CDN fetches don't count. | Free | Attribution to photographer + Unsplash required. Must ping `/photos/:id/download` when image is shown (enforced in review). |
| Pexels | 200 req/h, 20,000/month; unlimited on request | Free | Commercial OK, attribution appreciated. |
| Pixabay | 100 req / 60s per key; increasable | Free | Commercial OK, attribution optional. |

## Proposed Architecture

```
backend/shared/providers/images/
├── __init__.py
├── base.py                  # ImageProvider ABC, normalized HeroImage dataclass
├── wikimedia.py
├── europeana.py
├── loc.py
├── smithsonian.py
├── met.py
├── unsplash.py              # fallback
└── selector.py              # Tier-1 → Tier-2 cascade + scoring
```

Skill / API surface (single entry point so the frontend stays dumb):

```python
# backend/apps/web/skills/get_chat_header_image.py (sketch)
async def get_chat_header_image(topic: str, lang: str) -> HeroImage:
    """Returns {url, source, attribution, license, width, height, focal_point}."""
```

`HeroImage` is stored in Postgres on the chat row (encrypted alongside other chat metadata) so it survives reloads and syncs cross-device. The frontend renders via `proxyImage()` so we don't leak topics to third parties at view time.

### Selection Pipeline

1. **Topic extraction** — reuse the existing post-processing topic extractor (the same one feeding daily inspiration). For brand-new chats with no topic yet, fall back to a category-level default per Mate.
2. **Source cascade** — query Wikimedia → Europeana → LoC → Smithsonian → Met → Rijksmuseum → NASA in parallel; collect candidates with metadata.
3. **Quality filter** — minimum 1600px width, landscape aspect 16:9 ± 0.3, prefer "Featured pictures" / "Quality images" Commons categories where present.
4. **Safety filter** — Commons category blocklist (war atrocities, medical, colonial degrading content) + lightweight NSFW classifier on the candidate thumbnail before commit. Reuse logic from `docs/architecture/image-safety-pipeline.md` where applicable.
5. **Score** — weighted by source priority, resolution, license clarity (CC0 > CC BY > CC BY-SA), and topic-match (TF-IDF on title + description).
6. **Fallback** — if no Tier-1 candidate scores above threshold, query Unsplash (or Pexels). If those also fail, leave the header empty rather than show a low-quality image.
7. **Cache** — `(topic_hash, lang) → HeroImage` in Postgres + Redis (30 days). Almost all rate-limit pressure disappears with the cache.

## Embeddings-Based Matching (Idea)

Instead of (or in addition to) keyword/TF-IDF matching against image titles + descriptions, we could match by **vector embeddings**:

- Pre-compute CLIP (or similar multimodal) embeddings for a curated subset of each provider's catalog — e.g. the top ~100k Wikimedia "Quality images" + top ~50k Europeana `reusability=open` IMAGE results + the full Smithsonian / Met / Rijksmuseum CC0 catalogs.
- Store vectors in pgvector (we already use Postgres) alongside the image metadata + license.
- At chat-creation time: embed the topic string with the same model, run an ANN search, return the top N candidates, then apply quality + safety filters.
- Re-embed once per quarter to pick up new uploads.

**Why this could be better than keyword matching:**

- Handles abstract / conceptual topics ("loneliness in the digital age") that have no obvious keyword overlap with image captions.
- Cross-language for free — CLIP embeds visual concepts, not English words.
- Composes naturally with the existing semantic chat search infra (`docs/architecture/frontend/semantic-chat-search.md`) — we already pay the embedding-pipeline tax.

**Why it might not be worth it:**

- Cost of pre-computing embeddings for hundreds of thousands of images is one-time but non-trivial.
- Storage: a 768-dim float32 vector × 200k images × ~4 providers ≈ 2.5 GB in pgvector. Manageable but not free.
- Cold-start: until the index is built, we'd still need a keyword fallback anyway — so we'd have to maintain both paths.
- For "magazine cover" use-case, source-quality (Featured pictures, FSA, Met OA) probably matters more than semantic precision. A bad-but-relevant photo is worse than a beautiful-but-loosely-related one.

**Decision needed:** start with keyword + scoring, add CLIP embeddings as a Phase 2 if topic coverage feels weak in dogfooding. Or commit to embeddings from day one because it's where this is heading anyway.

## Cropping & Aspect-Ratio Problem (Concern)

The single hardest problem with this feature isn't fetching images — it's making them **look good in the chat header** at every viewport. Source images have wildly varying aspect ratios (square paintings, tall portraits, panoramic landscapes, scanned newspaper pages). The header is a fixed-aspect strip (probably ~16:9 or wider on desktop, shorter on mobile). Naive `object-fit: cover` will:

- Cut off heads, faces, and key subjects.
- Place the most interesting content off-screen.
- Make portrait-oriented historical photos (a huge fraction of the LOC and Met collections) look terrible.

**Possible approaches, ranked roughly by effort:**

1. **Hard filter on landscape aspect ratio at fetch time** — only accept images with aspect ≥ 1.5:1. Loses huge swathes of the most beautiful historical material (almost all 19th-century portrait photography), but trivially scales.
2. **Provider-supplied focal points** — a few APIs (Unsplash) return a focal point or face crop. Most don't.
3. **Smart-crop via saliency / face detection** — run a lightweight model (e.g. `smartcrop.py`, OpenCV saliency, or a small ONNX face detector) at ingest time, store a `focal_point: {x, y}` per image, use CSS `object-position` to anchor the crop. Reasonable cost, big quality win. Already infra-adjacent — `image-safety-pipeline.md` runs models on images anyway.
4. **AI-driven "extend image" (outpainting)** — use a generative model to extend tall images sideways into a header-shaped canvas. Too expensive, ethically dubious for historical archives (we'd be inventing parts of historical photographs).
5. **Letterbox + blurred backdrop** — show the full image centered with a blurred version of itself filling the rest of the header. Universal, never crops badly, has a "magazine cover" feel. Probably the safest default.
6. **Curated hand-picked set per category** — bypass the dynamic-fetching problem entirely for the top ~200 most common chat topics by hand-picking + hand-cropping. Doesn't scale to long-tail topics but guarantees beauty for the common case.

**Likely answer:** combine #5 (letterbox-blur as the universal fallback that never looks broken) with #3 (smart-crop with focal-point detection at ingest, used when the source aspect is close to header aspect). Skip #1 because it throws away too much. Maybe layer #6 on top for the top 50 topics if we want a really polished launch.

This deserves its own design spike — building 4–5 visual mockups and seeing which actually look good with real images is much higher signal than further written analysis.

## Open Questions

- Should the hero image be **per chat** (chosen at create time, frozen) or **dynamic** (re-computed when the topic shifts mid-conversation)? Per-chat is simpler and matches a "magazine cover" feel; dynamic is more reactive but visually noisy.
- How do we expose **provider attribution** in the UI? Tooltip on hover, or a small caption strip below the header?
- Do we want **user override** — let users pick from the top 5 candidates or upload their own?
- Should historical-photo bias be a **per-Mate setting** (e.g. History Mate → archival, Code Mate → modern abstract)?
- **Licensing storage** — minimum we must store per image: source name, original URL, photographer/contributor, license SPDX identifier, license URL. Where in the chat schema?
- **Embeddings vs keyword matching** — start with keyword + scoring and add CLIP embeddings as Phase 2, or commit to embeddings from day one? (See "Embeddings-Based Matching" section above.)
- **Cropping strategy** — letterbox-blur fallback + smart-crop focal points, or hard-filter to landscape aspect only? Needs a visual design spike with real images. (See "Cropping & Aspect-Ratio Problem" section above.)

## Watch-outs

- **Wikimedia User-Agent** — generic UAs are blocked. Send `OpenMates/<version> (contact@<PLACEHOLDER>)`.
- **Unsplash download tracking** — must hit `/photos/:id/download` when the image is actually displayed; enforced in their review process.
- **Per-image licenses** — Commons and Europeana mix CC0 / CC BY / CC BY-SA. Always store per-image, never assume per-API.
- **Europeana 2026 governance** — confirm public APIs remain free & open before shipping.
- **Hotlinking vs proxy** — always proxy through `imageProxy.ts` so user topics never leak to third parties at view time and so we control caching/resizing.
- **Disturbing historical content** — archives include graphic war and medical material. The safety filter is non-optional.

## Related

- [Daily Inspiration](./daily-inspiration.md) — adjacent feature, shares topic-extraction logic
- [Image Safety Pipeline](../image-safety-pipeline.md) — reuse for hero image safety filter
- OPE-307 — image search skill providers (Flickr, Wikidata) — share provider wrappers where possible
- OPE-24 — OG images for shared chats — could reuse the same hero image selection pipeline
