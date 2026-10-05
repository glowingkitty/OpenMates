---
title: Svelte coding rules
description: Reliable Svelte components, reactive state, effects and UI semantics.
when_to_use: Writing or changing Svelte components or reactive modules. Apply runes guidance only where the project uses Svelte 5 runes.
---
Use the project's installed Svelte version and component conventions. Svelte 5
supports legacy components; applying this guide does not require a migration.

- Keep mutable source values in state. Compute dependent values with side-effect-free
  derived expressions rather than synchronizing copies through effects.
- Reserve effects for browser or external side effects. Effects do not execute
  during server rendering, so essential rendered state must not depend on them.
- Remember that effect dependencies come from synchronous reads. Reads after an
  await or inside a later timer do not automatically become tracked dependencies.
- Return cleanup for listeners, subscriptions, timers and requests that need it.
  Keep an onMount callback synchronous when relying on its returned cleanup;
  start asynchronous work inside it and cancel obsolete work appropriately.
- Understand state proxy and raw-state semantics. Ordinary destructuring can
  capture an old value instead of maintaining its reactive relationship.
- Type component props and respect parent-owned state. Make two-way binding an
  explicit interface decision instead of mutating values owned by another component.
- Use stable identity keys for changing lists where item identity matters.
  Prefer native semantic controls with correct labels and keyboard behavior.
- Check version support before using newer conveniences; derived-value overrides
  require Svelte 5.25 or later. Verify the visible behavior and cleanup paths affected
  by a change using the project's existing test patterns.

These practices do not replace required project behavior, approved Specifications
or mandatory tool protocols.

References reviewed 2026-10-04: [state](https://svelte.dev/docs/svelte/$state),
[derived](https://svelte.dev/docs/svelte/$derived), [effects](https://svelte.dev/docs/svelte/$effect),
[lifecycle](https://svelte.dev/docs/svelte/lifecycle-hooks), [props](https://svelte.dev/docs/svelte/$props),
[each blocks](https://svelte.dev/docs/svelte/each), [TypeScript](https://svelte.dev/docs/svelte/typescript).
