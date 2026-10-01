# Apps workspace Figma comparison

Reviewed implementation: `41cc2179a426f0c96da99b68450ebf8b7e6e1cb6`.
CI harness: `afc642c99763f2c3b1f495966e491738a3ebf4a8`.
Review date: 2026-10-01.

The rendered web UI was compared directly with all three supplied artboards. All six Apps workspace screenshots and both Audio form screenshots were inspected. The layout hierarchy and responsive controls pass the comparison within the approved current Chats shell baseline.

| Figma reference | Rendered views | Confirmed appearance and interaction |
| --- | --- | --- |
| [6019:61646](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6019-61646) | Apps home, 1180 and 390 px | Daily Inspiration above the greeting/prompt; one app-card row; loaded Web/Health glyphs; visible, unobstructed Show all/Search; bottom skill chooser; inspiration action opens a skill. |
| [6021:60395](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6021-60395) | Health app fullscreen, laptop and phone | Tall gradient hero with app identity/actions/counts; all five floating tabs; white inner card with centered, wrapping skill cards; contained phone layout. |
| [6022:77555](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6022-77555) | Web Search fullscreen and Audio direct-use form, laptop and phone | Three floating skill tabs; loaded Search hero glyph; coral Use skill action focuses the primary field; grey Audio textarea; gear Show settings control; coral form action; stacked provider/rate/model details. |

The current Chats shell supplies the shared outer layout and continue-card sizing. At 1180 px the home carousel shows two complete cards and part of a third; the wider Figma desktop frame shows three. The public preview displays “Apps” instead of a signed-in username. App names, colors, counts, field labels, providers/models, defaults and prices come from current metadata. Audio retains its declared 1.0-second default and 20 credits per second. Generic schema forms use “Run skill”; tab glyphs reuse the repository icon set, including Search for Focus modes and the existing skill Overview glyph. This review confirms the design hierarchy and working controls without claiming pixel-identical content or icons.

## Evidence

[Workspace component CI and six screenshots](https://github.com/glowingkitty/OpenMates/actions/runs/36808696995/artifacts/11138810962): seven cases passed, with no skips or flaky cases. The artifact includes `apps-home-1180.png`, `apps-home-390.png`, `app-detail-1180.png`, `app-detail-390.png`, `skill-detail-1180.png` and `skill-detail-390.png`.

[Form component CI and Audio screenshots](https://github.com/glowingkitty/OpenMates/actions/runs/36808703802/artifacts/11138671195): seven cases passed, with no skips or flaky cases. The artifact includes `audio-form-desktop.png` and `audio-form-phone.png`.

The automated checks cover actual SVG path data, all five app-tab hitboxes, heading/banner separation, horizontal containment, unobstructed catalog links, primary-input focus, schema defaults, advanced controls, and declared pricing/provider/model information.

All eight screenshots from this final reconciled source are byte-identical to the directly inspected prior renderings. The reconciliation preserves Apps layout and controls while retaining the latest shared workflow navigation.
