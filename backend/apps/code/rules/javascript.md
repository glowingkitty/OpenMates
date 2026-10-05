---
title: JavaScript coding rules
description: Predictable JavaScript values, modules, promises and browser work.
when_to_use: Writing or changing JavaScript or JavaScript runtime logic inside framework files.
---
Use the project's runtime and framework conventions. Preserve their escaping,
lifecycle and module boundaries when applying general JavaScript practices.

- Keep imports and dependency boundaries explicit and compatible with the target
  runtime. Check support before adopting new syntax or APIs.
- Choose nullish and falsy fallbacks deliberately. Zero, false and an empty string
  may be valid values that must survive a fallback operation.
- Observe promise rejection and check HTTP status separately. A resolved fetch
  promise does not establish that the server returned a successful status.
- Choose promise aggregation for the required success and failure semantics.
  Promise.all rejection does not cancel the remaining operations; arrange cleanup
  or cancellation separately where the work needs it.
- Give requests a lifecycle owner. Abort obsolete requests when the API supports
  a signal, and prevent late results from overwriting newer state.
- Distinguish mutating array operations from operations returning copies. Sorting
  a shared array can change another caller's state unexpectedly.
- Keep untrusted strings out of unsafe HTML sinks. Prefer text APIs or the
  framework's escaping; use established sanitization when HTML rendering is required.
- Verify meaningful success, failure and obsolete-result behavior rather than
  relying on a static type or a happy-path response alone.

This guide supplies reusable practices. It grants no access and does not relax
mandatory security or tool protocols.

References reviewed 2026-10-04: [modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules),
[nullish coalescing](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/Nullish_coalescing),
[promises](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Using_promises),
[fetch](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch),
[Promise.all](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all),
[AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController),
[array sorting](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort),
[innerHTML](https://developer.mozilla.org/en-US/docs/Web/API/Element/innerHTML).
