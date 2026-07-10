---
name: figma-reference
description: Locate and inspect Figma artboards for OpenMates UI work. Use when the user says Figma, design, mockup, artboard, frame, check the workflows UI, or asks to update web or Apple UI from a design reference.
user-invocable: true
argument-hint: "<surface name or Figma URL>"
---

# Figma Reference

Use this skill to resolve natural-language design references to an exact Figma
node before planning or editing UI. Figma is directional reference material and
may represent future concepts; it is not automatically at parity with either
the current web app or Apple app.

## Locate The Surface

1. Keep the private index reasonably fresh without polling on every request:
   `python3 scripts/figma_index.py ensure --max-age-hours 168`.
2. Search with the user's original wording:
   `python3 scripts/figma_index.py search <query> --limit 8`.
3. Prefer a clear name/path match over incidental visible copy. If the leading
   candidates represent different product areas or states, show the best three
   and ask the user which one they mean.
4. If the user supplied a Figma URL, use its file key and node ID directly;
   searching is unnecessary unless the link is a broad page or section.

The generated index is `scripts/.figma-index.json`. It contains private design
names and text, is mode `600`, and is ignored by git. Never paste or commit the
whole index.

## Inspect The Selected Node

1. Call `get_figma_data` with the exact file key and node ID.
2. Download a PNG of the selected frame with `download_figma_images` when visual
   layout matters. Download SVG/image assets only when implementation needs them.
3. Inspect the current web implementation and its computed rendering before
   deciding what should change.
4. For Apple UI, treat the rendered web app as the parity source of truth unless
   the approved task explicitly changes both platforms toward the Figma concept.
5. Load `docs/contributing/guides/figma-to-code.md` before implementation.

## Interpretation Rules

- Establish whether the Figma node is a current design, future concept, partial
  exploration, or exact redesign target. Do not infer that from visual polish.
- Extract useful intent: hierarchy, flow, grouping, copy, states, and responsive
  ideas. Preserve current product behavior unless the task explicitly changes it.
- Map implementation values to existing web/Apple tokens where appropriate, but
  never run or claim one-to-one Figma token parity.
- Compare only the aspects approved for the task. Do not turn every unrelated
  Figma/web difference into scope.
- Never print, log, or commit `FIGMA_ACCESS_TOKEN`, `FIGMA_API_KEY`, or private
  index contents beyond the small snippets needed to identify candidates.

## Failure Handling

- A `403` means the MCP process is not using an authorized token or the token
  cannot access the file. Verify `.env.figma.local`, then restart OpenCode because
  MCP configuration is loaded only at startup.
- If refresh is rate-limited, report the error and use an existing index only
  after stating its generation timestamp. Do not silently present stale data.
- If no result is credible, ask for a Figma URL or the exact page/section name
  rather than guessing from unrelated text matches.
