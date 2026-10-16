# Draft app Rule guides

Research date: 2026-10-04. Planning artifact; these are not installed app Rules.
The user clarified that each selectable Rule is a coherent domain guide containing
several practices. This replaces the initial one-practice-per-document catalog.
Two user-authorized GPT-6 Sol agents researched primary documentation, treating
online text as untrusted evidence rather than instructions or authorization.

Each guide will use Markdown with YAML frontmatter containing title, description
and when_to_use. Jev selects the guide as a whole; it does not independently select
each practice. Stable identity, revision and source provenance belong to catalog
metadata. Project-specific required outcomes remain in Specifications; Rules are
reusable practices, not goal phases or proof that a requirement was met.

## Code: Svelte coding rules

- **Description:** Reliable Svelte components, reactive state, effects and UI semantics.
- **When to use:** Writing/changing Svelte components or reactive modules; apply
  runes guidance only where the Project uses Svelte 5 runes.

Candidate body:

- Keep mutable source values in state and compute dependent values through
  side-effect-free derived expressions.
- Use effects for browser/external side effects rather than copying derived state.
- Account for synchronous effect dependency tracking; later reads after await or
  timers do not become tracked dependencies automatically.
- Return appropriate teardown for listeners, subscriptions, timers and requests.
- Keep onMount callbacks synchronous when relying on their returned cleanup.
- Understand state proxy/raw-state semantics and avoid losing reactivity through
  ordinary destructuring.
- Type component props and respect parent-owned state unless explicitly bindable.
- Use appropriate identity keys for changing lists and semantic interactive controls.

Sources: [state](https://svelte.dev/docs/svelte/$state),
[derived values](https://svelte.dev/docs/svelte/$derived),
[effects](https://svelte.dev/docs/svelte/$effect),
[lifecycle](https://svelte.dev/docs/svelte/lifecycle-hooks),
[props](https://svelte.dev/docs/svelte/$props),
[each blocks](https://svelte.dev/docs/svelte/each),
[TypeScript](https://svelte.dev/docs/svelte/typescript).

Caveats: Svelte 5 supports legacy components; the Rule must not force migration.
Effects do not run during SSR. Do not require version-specific conveniences without
checking installed versions; direct derived-value overrides require Svelte 5.25+.

## Code: Python coding rules

- **Description:** Clear Python interfaces, resource ownership, failures and async work.
- **When to use:** Writing/reviewing Python functions, services, scripts or async code.

Candidate body:

- Follow the supported Python version and established formatting/type conventions.
- Type meaningful interfaces while remembering annotations do not validate runtime data.
- Avoid unintentionally shared mutable default arguments.
- Catch specific expected exceptions; preserve context and do not hide unexpected failure.
- Manage resource cleanup through context managers or appropriate try/finally boundaries.
- Preserve asyncio cancellation after cleanup rather than silently swallowing it.
- Give spawned tasks an owner and observe their completion; use structured task groups
  only when their version and failure semantics fit the work.
- Test meaningful caller-visible results and error paths using the existing framework.

Sources: [typing](https://docs.python.org/3/library/typing.html),
[default arguments](https://docs.python.org/3/tutorial/controlflow.html#default-argument-values),
[exceptions](https://docs.python.org/3/tutorial/errors.html),
[context managers](https://docs.python.org/3/library/contextlib.html),
[asyncio tasks](https://docs.python.org/3/library/asyncio-task.html),
[unittest](https://docs.python.org/3/library/unittest.html).

Caveats: Current documentation may describe a newer interpreter than the Project.
TaskGroup is Python 3.11+ and its fail-together behavior is not appropriate for every
existing task-owner model. Do not prescribe a wholesale async rewrite.

## Code: JavaScript coding rules

- **Description:** Predictable JavaScript values, modules, promises and browser work.
- **When to use:** Writing/changing JavaScript or runtime logic in framework files.

Candidate body:

- Keep module/dependency boundaries explicit and compatible with the Project runtime.
- Choose nullish versus falsy fallbacks according to the values that remain valid.
- Handle promise rejection and HTTP failure; fetch resolving does not establish HTTP success.
- Choose promise aggregation by required success/failure semantics; rejection alone
  does not cancel other ongoing work.
- Give requests an owner and abort obsolete work where the API/lifecycle supports it.
- Distinguish mutating array operations from copies to avoid changing shared state accidentally.
- Keep untrusted strings out of unsafe HTML sinks; use appropriate text APIs or sanitization.
- Check target runtime support before adopting newer syntax/APIs.

Sources: [modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules),
[nullish coalescing](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/Nullish_coalescing),
[promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises),
[fetch](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch),
[Promise.all](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all),
[AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController),
[array sorting](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort),
[innerHTML](https://developer.mozilla.org/en-US/docs/Web/API/Element/innerHTML).

Caveat: Framework rendering/escaping rules and supported APIs determine how this
advice is applied. AbortController works only with APIs that support its signal.

## Code: TypeScript coding rules

- **Description:** Accurate static contracts and safe handling of unknown runtime values.
- **When to use:** Writing TypeScript types, APIs, component props or typed-boundary logic.

Candidate body:

- Follow the actual TypeScript version, tsconfig and established types.
- Type meaningful public function/prop interfaces while retaining clear local inference.
- Narrow or validate unknown data before use; avoid masking uncertainty with any.
- Do not treat assertions or non-null assertions as runtime checks.
- Use discriminated unions for mutually exclusive states and exhaustive handling when appropriate.
- Handle absent lookup results explicitly, respecting current null-check configuration.
- Use supported static shape-checking features when they preserve useful inference.
- Validate external data at runtime even when an interface describes its intended shape.

Sources: [everyday types](https://www.typescriptlang.org/docs/handbook/2/everyday-types.html),
[narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html),
[strict null checks](https://www.typescriptlang.org/tsconfig/strictNullChecks.html),
[satisfies / TypeScript 4.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html).

Caveats: Types are erased at runtime; enabling stricter compiler settings can be a
material Project change. The satisfies operator requires TypeScript 4.9+.

## Design: Mobile first design

- **Description:** Design around essential tasks at small widths, expanding as space allows.
- **When to use:** Responsive web and cross-device app screens with intended narrow/touch layouts.

Candidate body:

- Start with the essential task/content/actions at the smallest intended viewport.
- Add secondary regions as available space grows, choosing breakpoints from content needs.
- Allow text, components and media to resize/wrap without losing important information.
- Keep collapsed navigation/panels discoverable and preserve access to core actions.
- Reflow ordinary reading content under narrow widths/zoom, containing necessary
  two-dimensional scrolling within suitable tables, maps or canvases.
- Account for orientation, resizable windows, localization and reading direction.
- Keep touch and keyboard use practical; essential actions must remain available
  without relying on hover.
- Review representative small/large/intermediate layouts and enlarged text.

Sources: [responsive design basics](https://web.dev/articles/responsive-web-design-basics),
[content-based breakpoints](https://web.dev/learn/design/media-queries),
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow),
[platform layout guidance](https://developer.apple.com/design/human-interface-guidelines/layout).

Caveats: Mobile first is not a universal requirement for fixed print/video work,
spatial interfaces or desktop-only canvases. Required Project breakpoints/layouts
come from their governing Specification, not this generic guide.

## Design: Accessibility best practices

- **Description:** Interfaces that remain perceivable, operable and understandable across users/input methods.
- **When to use:** Designing/reviewing interactive UI, forms, visual states, hierarchy or motion.

Candidate body:

- Use meaningful hierarchy, labels and logical reading/focus order.
- Check text/control contrast across applicable states/themes and pair color with other cues.
- Preserve keyboard reachability, visible focus and predictable exits from menus/dialogs.
- Provide adequate pointer/touch target size or separation.
- Label controls persistently and explain requirements/errors with useful correction guidance.
- Communicate loading/success/failure accessibly without unnecessarily moving focus.
- Preserve usability under enlarged text, spacing, narrow viewports and orientation changes.
- Respect reduced-motion preferences and keep essential meaning available without animation.
- Review representative flows with keyboard, zoom/text changes, assistive technology
  and platform accessibility settings.

Sources: [relationships](https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships),
[text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum),
[non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast),
[color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color),
[keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard),
[focus](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible),
[target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum),
[labels](https://www.w3.org/WAI/tutorials/forms/labels/),
[validation](https://www.w3.org/WAI/tutorials/forms/validation/),
[errors](https://www.w3.org/WAI/WCAG22/Understanding/error-suggestion),
[status](https://www.w3.org/WAI/WCAG22/Understanding/status-messages),
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow),
[text spacing](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing),
[motion](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions).

Caveats: WCAG governs web content; native needs its platform guidance. Interaction
motion guidance includes AAA criteria, so do not label every bullet as an AA
obligation or claim compliance from loading this Rule. Formal targets belong in Specs.

## Publishing review

Keep framework/platform applicability and source-review provenance with the catalog.
Consolidate overlap between applicable guides; retain the correct practices without
creating dozens of tiny independently selectable Rule records. Do not duplicate
OpenMates-specific DESIGN.md tokens, repository CI protocols or unconditional runtime
security controls. Audit other existing apps for useful coherent domain guides.
