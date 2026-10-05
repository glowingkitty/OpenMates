---
title: Mobile first design
description: Design around essential tasks at small widths, expanding as space allows.
when_to_use: Designing responsive web or cross-device app screens with intended narrow and touch layouts.
---
Begin with the smallest intended layout and the user's essential task. This is
not a universal layout prescription for print, video, spatial interfaces or
desktop-only canvases. Required layouts come from governing Specifications.

- Prioritize essential content and actions at small widths. Add secondary regions
  as space becomes available without hiding necessary steps.
- Choose breakpoints from content needs rather than particular device names.
  Inspect intermediate widths where wrapping and overflow often appear.
- Let text, controls and media resize or wrap while preserving important
  information and usable actions.
- Keep collapsed navigation and panels discoverable. Core actions must remain
  reachable when a sidebar or secondary area becomes hidden.
- Reflow ordinary reading content under narrow widths and zoom. Contain necessary
  two-dimensional scrolling within suitable tables, maps or canvases rather than
  forcing the whole page to scroll horizontally.
- Account for orientation, resizable windows, localization, reading direction
  and text enlargement instead of assuming one phone-sized screenshot.
- Make touch and keyboard operation practical. Essential information and actions
  must remain accessible without hover.
- Review representative small, intermediate and large layouts with enlarged text.
  Use the relevant native platform guidance for native layouts.

This guide supplies layout practices, not a new set of required project
breakpoints or permission to change approved product behavior.

References reviewed 2026-10-04: [responsive design basics](https://web.dev/articles/responsive-web-design-basics),
[content-based breakpoints](https://web.dev/learn/design/media-queries),
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow),
[platform layout](https://developer.apple.com/design/human-interface-guidelines/layout).
