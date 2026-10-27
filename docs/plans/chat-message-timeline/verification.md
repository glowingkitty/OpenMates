# Chat message timeline verification

Current Specification: `feature.chat-message-timeline@1`, approved mobile disclosure
fingerprint `a073425ba3eab4f310c1504392473c63337aa81a7f04b5ab81b6e89696b34649`.

Narrow chat panes retain their ordinary transcript width. A matching toolbar
button opens a persistent gray timeline pill over the left of the transcript;
opening and closing fade smoothly and change button opacity without reflow or
scroll movement. The wide-screen rail remains automatic beside the message lane.

| Required check | Result | Evidence |
| --- | --- | --- |
| Focused frontend units, scoped lint and Svelte compilation | Passed | 14 unit cases, all 49 tracked-file lint checks, and six changed components compiled without warnings |
| Phone touch, narrow-pane disclosure, themes, keyboard and reduced motion | Passed | 13 isolated component cases, no retries; [run 40092960257](https://github.com/glowingkitty/OpenMates/actions/runs/40092960257), source `9256a56cccaec3e5169bf4a158536f4afb0df7a4`; final dark phone and light narrow-pane captures reviewed |
| Actual toolbar and encrypted 10,000-exchange history | Passed | [Run 40094496429](https://github.com/glowingkitty/OpenMates/actions/runs/40094496429), source `8fe4c6e27de6e5c7a852c2f4c9d5a5dd95787315`; no retries; mobile old-section loading, persistent disclosure, width/scroll preservation, bookmark reload/retry and unchanged compression/inference state |
| Scoped dev deployment and reviewed laptop/phone screenshots | Passed | Product commit `c0a19ab4565f35e8d57034d999f3a6cc68653fe4`; exact frontend build ready; reviewed `test-results/visual-smoke/b026-mobile-timeline-20261024/summary.json` with zero overflow, broken images, console/page errors, failed requests or bad responses. Defects: none. Accepted differences: none. |

The component and full-flow candidates have identical UI bytes. Only the broader
flow test and its generated assertion index changed after component proof.
The phone case confirms that previewing an unloaded exchange preserves the
transcript until release, then renders the selected exchange at its reachable
scroll boundary. Long-history cases retain exact 70px anchor checks. Reopening
a long stack reveals the current exchange rather than the first marks.

Retained baseline protection checks remain applicable to unchanged headless and
backend paths: 16 Python catalogue cases, 22 Directus cases and 92 focused
authentication hydration/access cases. This mobile change does not alter catalogue
permissions, encrypted settings, selected-section reads or AI memory.

Selected component and full-flow recordings uploaded successfully; their source
and run inventories remain in the corresponding CI receipts. No selected capture
or upload failures remain.
