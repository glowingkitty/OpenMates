# Chat message timeline verification

Corrected Specification: `feature.chat-message-timeline@1`, approved fingerprint
`59878f46bed8fd9bb1d40d0e29f534109a8e00c675b957a53f69d0da719bf632`.
The user approved compact, scrollable marks beside the message column and
assistant-only bookmarks using the existing delayed tooltip UI.

| Required check | Result | Evidence |
| --- | --- | --- |
| Exchange counting, pairing, preview extraction and legacy bookmark compatibility | Passed | 14 focused frontend unit cases |
| Svelte, TypeScript, design tokens, YAML and whitespace | Passed | Scoped session lint and `git diff --check` |
| Short/dense/wide/phone layouts, header boundary, touch and fixed assistant actions | Passed | 11 isolated component cases, no retries; [run 39996744577](https://github.com/glowingkitty/OpenMates/actions/runs/39996744577), source `87fe11b02ce79502007f7fe2823e81cd26f41f7b`; wide/phone header and corrected report-icon frames reviewed |
| Real encrypted 10,000-exchange history, compression, private persistence and retry | Passed | Real encrypted 10,000-exchange flow, no retries; [run 39998390045](https://github.com/glowingkitty/OpenMates/actions/runs/39998390045), same source; preview, old section and latest frames reviewed |
| Scoped dev deployment and reviewed laptop/phone screenshots | Passed | Product commit `483f210983cbe164cdc9e03502f7d9b5c066e972`; exact frontend build ready; reviewed laptop/phone capture `test-results/visual-smoke/b026-corrected-timeline-20261023/summary.json` |

Retained baseline protection checks passed before this presentation correction:
16 Python catalogue cases, 22 Directus cases, and 92 focused authentication
hydration/access cases. This correction preserves the bounded catalogue,
selected-section access/encryption paths and opaque account-settings hydration.
No inference or compression behavior changes are included.

The earlier far-left implementation's public-example smoke reported an unrelated
signed-out `/v1/projects/focus/current` request returning 401. That result remains
recorded under `test-results/visual-smoke/b026-timeline-20261023/`; it is not proof
of this corrected implementation. No unrelated Project-focus repair is included.

The reviewed component captures show the complete header inside the viewport,
with the compact rail below it and beside the message lane. The report control
retains its existing thumbs-down orientation. Desktop tooltip checks assert
fixed control positions, while the phone checks retain 44-pixel touch controls.

The deployed public example has nine evenly spaced marks in a 108-pixel stack.
Both viewports preserve the full-width header and clamp the rail beneath it.
The smoke reports zero horizontal overflow, broken images, console/page errors,
failed requests or bad responses. Defects: none. Accepted differences: none.

Selected component and full-flow recordings uploaded successfully; their
immutable source/run inventories remain under the corresponding CI receipts.
