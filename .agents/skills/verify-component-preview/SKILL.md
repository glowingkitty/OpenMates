---
name: verify-component-preview
description: Use whenever adding or modifying a web UI element, Svelte component, screen, icon, hover state, focus state, or responsive layout. Enforces bare URL-configured component proof before broader use-case specs.
---

# Verify Component Preview

Use this workflow after the API/CLI/SDK gates that apply to shared behavior and
before implementing or running a broader route-level or use-case Playwright
spec. If Figma is involved, run `figma-reference` first.

## Required Order

1. Identify every component materially changed by the task.
2. Ensure each component has a colocated `ComponentName.preview.ts` fixture
   with one semantically valid default state and named variants where static
   state differs.
3. Open the deployed component in bare capture mode. The canonical URL is:
   `https://app.dev.openmates.org/dev/preview/{component-path}?theme=light&background=%23dbeafe&width={width}&chrome=0`.
4. Confirm the page shows only the component on the requested background. The
   preview toolbar, component catalogue, breadcrumb, props editor, variant bar,
   viewport guides, and status bar must not be visible.
5. If no focused component spec exists, create it under
   `frontend/apps/web_app/tests/components/`. Keep component specs separate
   from route-level and full use-case specs.
6. In the focused spec, drive meaningful hover, focus, keyboard, click,
   expanded/collapsed, on/off, loading, empty, error, and responsive states that
   apply to the component. Assert layout geometry, control visibility, icon
   presence, readable labels, clipping/overflow, and interaction results before
   each named proof checkpoint.
7. Deploy, run the focused component spec, review its component-only proof, and
   fix objective defects before creating, extending, or running the broader
   use-case spec.

## Component Spec Contract

- Include `// playwright-account: not_required reason=isolated_component_preview`
  when the fixture performs no authenticated server action.
- Navigate only to a URL-configured bare preview with `chrome=0`.
- Use query parameters for `theme`, `background`, `width`, `variant`, and
  `props` as needed; do not operate the old preview controls to configure state.
- Assert the component and its behavior directly. Never use
  `preview-toolbar`, `preview-back-link`, `breadcrumb-name`,
  `preview-status-bar`, the props editor, or the component catalogue as proof
  that a component rendered correctly.
- The preview route's internal readiness marker may be used only to wait for
  mounting. It is not a product assertion or proof checkpoint.
- Use phone and laptop profiles only when responsive behavior differs.
- Publish the focused component video before moving to full-flow verification.

## Stop Conditions

Do not continue to the broader use-case spec when the focused component has a
missing or wrong icon, hidden control, overlap, clipping, overflow, invalid
default state, broken hover/focus/click behavior, render error, or unexplained
responsive difference. Fix and rerun the component spec first.

Do not modify a component or component spec owned by another live session.
Report the exact conflicting file and continue with non-conflicting workflow
or audit work.
