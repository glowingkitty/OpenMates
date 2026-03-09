# Figma-to-Code — Rules

Rules for implementing UI components from Figma designs. For full phase-by-phase guide and component patterns, run:
`python3 scripts/sessions.py context --doc figma-to-code-ref`

---

## Three Phases — Never Skip

1. **Design Interpretation** — extract data from Figma, map to design system, ask questions
2. **Implementation** — write Svelte 5 code following frontend standards
3. **Visual Validation** — compare against Figma using component preview system or Firecrawl

## Phase 1 Rules

### Extract Before Coding
Use Figma MCP (`get_figma_data`, `download_figma_images`) to extract layout, typography, colors, spacing, and component hierarchy. Query ALL breakpoints if multiple frames exist.

### Map to Design System First
Map every Figma value to existing tokens in `theme.css` before considering new ones. Never hardcode hex colors. If a color doesn't match any token (±5 RGB), flag it.

### Search for Reusable Components
Before creating anything new, search `frontend/packages/ui/src/components/` (273+ components). Key bases: `UnifiedEmbedPreview`, `UnifiedEmbedFullscreen`, `Button`, `Field`, `Toggle`.

### Always Ask Clarifying Questions
Before coding, ask about:
1. Responsive behavior (if only one breakpoint in Figma)
2. Interactive states (hover, active, disabled, loading)
3. Data flow (which parts are dynamic props?)
4. Component reuse (extend existing vs create new?)
5. Dark mode support

### Present Plan and Wait
Present an implementation plan listing new files, modified files, design tokens used, responsive strategy, and component composition. Wait for user confirmation.

## Phase 2 Rules

- Svelte 5 runes only — never `$:`
- CSS custom properties only — never hardcoded hex
- TypeScript strict — define `interface Props`
- Mobile-first responsive
- Create `.preview.ts` companion files for dev preview
- Run linter before Phase 3

## Phase 3 Rules

- Use component preview system (`/dev/preview/`) or Firecrawl for validation
- Verify each breakpoint (desktop 1440, tablet 768, mobile 375)
- Check: layout, spacing (±1px), typography, colors, interactive states, dark mode, accessibility
- Fix in source code, never CSS injection or runtime patches
