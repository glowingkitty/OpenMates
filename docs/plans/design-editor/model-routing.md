# Design authoring model routing

Use the Design app skill for creation and modification. The normal assistant sends a short instruction. The skill selects a stronger author model, validates the typed result and asks Jev to judge whether its rendered draft meets the brief. Reuse the existing SVG generation structure for model calls, progress, metering and corrections. Keep the author and review prompts scoped to the requested work. An edit includes the permitted scene fragment, stable IDs and a base revision. Save the accepted result on the authorized client using the existing client-side encrypted embed pipeline.

## Evidence

| | Direct chat with Flash-Lite | Dedicated Design skill |
| --- | --- | --- |
| Quality | Typed JSON passed structural validation on 4 of 5 first replies. The flyer date was partly covered and an accepted follow-up clipped the longer headline. The dense typed request timed out. | A stronger author and a brief-specific visual review address different problems. Both real-inference flyer runs met the required copy. The candidate passed on the first draft and the deployed build accepted after one repair. The deployed flyer added an address the brief had not supplied. Both typed follow-ups passed on their first drafts. |
| Cost | 18 returned replies reported 338 credits across 20 attempts, about 18.8 per returned reply. The total covers all three formats and joint follow-ups. | Ordinary replies keep their existing routing. A Design action adds the short tool call, author, Jev review and a correction when needed. The candidate and deployed runs charged 19 and 29 credits for the flyer, and 10 and 9 for the follow-up. The chat turn is billed separately. |
| Latency | The four non-dense typed requests finished in 14.6–23.8 seconds. The dense typed request reached the CLI timeout at about 92 seconds. | The existing SVG author reports 7–24 seconds for low-reasoning SVG drafts in its author benchmark. That is a different task and excludes design-specific end-to-end latency. The flyer took 10.3 seconds on the candidate and 14.5 seconds with one repair on the deployed build. Both follow-ups took 2.2 seconds. These times cover the Design skill and review. |

Use the configured SVG lead model as the starting candidate, with a bounded fallback and correction budget shared across the request. Check required copy and text bounds deterministically first. Ask Jev to assess the intended copy, clipping, readability and layout on the rendered draft. Return compact diagnostics for one repair and review it again within the request budget. If the repair fails, report the unmet requirement and leave the current saved revision in place.

The first keyed Phase 3 run recorded an accepted flyer on its first Design draft at **14.4 seconds and 22 credits** for authoring and visual review. The client subsequently refused its reserved identifier, so this sample measures the skill through review. It omits chat routing, rendering and the saved result. The 338-credit Phase 0 total covers a different mix of calls across all three formats.

Phase 3 should compare time and credits per accepted design on the same five briefs. Keep the 250-layer cap while benchmarking a bounded grid representation for dense layouts. Count timed-out and invalid requests in acceptance rates. The flyer verifies the route for one of the five comparison briefs.

[Phase 0 format comparison](../design-editor-phase-0/format-comparison.md) · [SVG skill author](../../../backend/apps/images/vector_author.py)

## Export compatibility

The initial local exports are SVG, PDF and PNG. SVG and PDF open in Adobe Illustrator. [Adobe Illustrator supported file formats](https://helpx.adobe.com/illustrator/desktop/get-started/learn-the-basics/supported-file-formats-in-illustrator.html)

In view mode, SVG and PNG download the selected artboard. SVG retains text, shapes and paths as vector elements and includes embedded images. PNG uses the artboard's pixel dimensions. PDF contains every artboard in its original order and at its original proportions, with the page artwork flattened to preserve the Canvas appearance. All three are generated locally from the open Design and authorized images already available on the device. The saved Design remains client-side encrypted.
