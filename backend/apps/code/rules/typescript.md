---
title: TypeScript coding rules
description: Accurate static contracts and safe handling of unknown runtime values.
when_to_use: Writing TypeScript types, APIs, component props or logic at typed boundaries.
---
Follow the installed TypeScript version, tsconfig and established project types.
Compiler strictness changes can be a separate project decision.

- Type meaningful exported functions and component interfaces while retaining
  useful local inference. Keep contracts representative of the values callers receive.
- Narrow or validate unknown values before use. Avoid hiding uncertain boundary
  data behind any when an explicit check can establish its shape.
- Treat type assertions and non-null assertions as compile-time claims. They do
  not validate data or prevent a missing value at runtime.
- Use discriminated unions for mutually exclusive states when they clarify the
  model. Handle relevant alternatives exhaustively instead of permitting impossible
  combinations through unrelated optional properties.
- Handle absent lookup results explicitly and respect the project's null-check
  configuration. A declaration cannot guarantee that a runtime lookup succeeds.
- Use supported static shape checks when they preserve useful inference. The
  satisfies operator requires TypeScript 4.9 or later.
- Validate external data at runtime even when an interface describes its intended
  structure; TypeScript types are erased during compilation.
- Verify caller-visible behavior at uncertain boundaries, including absent or
  invalid data, alongside the appropriate existing compiler checks.

Use JavaScript runtime practices alongside this guide when relevant. Neither
guide changes approved behavior or mandatory access checks.

References reviewed 2026-10-04: [everyday types](https://www.typescriptlang.org/docs/handbook/2/everyday-types.html),
[narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html),
[strict null checks](https://www.typescriptlang.org/tsconfig/strictNullChecks.html),
[satisfies](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html).
