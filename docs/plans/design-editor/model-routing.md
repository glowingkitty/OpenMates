# Design authoring model routing

Use the Design app skill for creation and modification. The normal assistant sends a short instruction. The skill selects a stronger author model, validates the typed result and asks Jev to judge whether its rendered draft meets the brief. Reuse the existing SVG generation structure for model calls, progress, metering and corrections. Keep the author and review prompts scoped to the requested work. An edit includes the permitted scene fragment, stable IDs and a base revision. Save the accepted result on the authorized client using the existing client-side encrypted embed pipeline.

## Evidence

| | Direct chat with Flash-Lite | Dedicated Design skill |
| --- | --- | --- |
| Quality | Typed JSON passed structural validation on 4 of 5 first replies. The flyer date was partly covered and an accepted follow-up clipped the longer headline. The dense typed request timed out. | A stronger author and a brief-specific visual review address different problems. Design scene quality has yet to be measured on this route. |
| Cost | 18 returned replies reported 338 credits across 20 attempts, about 18.8 per returned reply. The total covers all three formats and joint follow-ups. | Ordinary replies keep their existing routing. A Design action adds the short tool call, author, Jev review and a correction when needed. Measure the total including fallbacks and timeouts. |
| Latency | The four non-dense typed requests finished in 14.6–23.8 seconds. The dense typed request reached the CLI timeout at about 92 seconds. | The existing SVG author reports 7–24 seconds for low-reasoning SVG drafts in its author benchmark. That is a different task and excludes design-specific end-to-end latency. Progress can appear before the reviewed result is ready. |

Use the configured SVG lead model as the starting candidate, with a bounded fallback and correction budget shared across the request. Check required copy and text bounds deterministically first. Ask Jev to assess the intended copy, clipping, readability and layout on the rendered draft. Return compact diagnostics for one repair and review it again within the request budget. If the repair fails, report the unmet requirement and leave the current saved revision in place.

Phase 3 should compare time and credits per accepted design on the same five briefs. Keep the 250-layer cap while benchmarking a bounded grid representation for dense layouts. Count timed-out and invalid requests in acceptance rates. The existing SVG result supports the architecture choice. It gives no measured quality, cost or latency advantage for editable scenes yet.

[Phase 0 format comparison](../design-editor-phase-0/format-comparison.md) · [SVG skill author](../../../backend/apps/images/vector_author.py)

## Export compatibility

The initial local exports are SVG, PDF and PNG. SVG and PDF open in Adobe Illustrator. [Adobe Illustrator supported file formats](https://helpx.adobe.com/illustrator/desktop/get-started/learn-the-basics/supported-file-formats-in-illustrator.html)
