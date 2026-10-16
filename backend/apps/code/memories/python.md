---
title: Python best practices
description: Clear Python interfaces, resource ownership, failure handling and asynchronous work.
when_to_use: Writing or reviewing Python functions, services, scripts or asynchronous code.
---
Fit changes to the project's supported interpreter, type conventions and resource
ownership model. Current documentation can describe a newer Python version.

- Type meaningful interfaces and keep local code clear. Annotations describe
  intended shapes; validate untrusted runtime input at the actual boundary.
- Avoid unintentionally shared mutable default arguments. Create per-call state
  inside the function when each invocation needs an independent value.
- Catch specific expected exceptions and preserve their context. Report useful
  failure to callers instead of masking unexpected errors as a successful result.
- Use context managers or try/finally to release owned resources, including
  resources opened before later work fails.
- Preserve asyncio cancellation after cleanup. Swallowing cancellation can break
  timeouts, structured concurrency and the caller's shutdown expectations.
- Give spawned tasks an owner, retain references where needed and observe their
  completion. Avoid detached failures and stale tasks continuing after their owner ends.
- Use TaskGroup only when the interpreter supports it and its fail-together
  semantics fit the operation. It requires Python 3.11 or later; do not rewrite
  established independent task ownership merely to adopt it.
- Test meaningful caller-visible results, expected failures and resource cleanup
  using existing fixtures and frameworks. Keep assertions focused on the behavior
  the change needs to preserve.

These practices guide implementation without changing the user's scope or
substituting for required Specification and permission checks.

References reviewed 2026-10-04: [typing](https://docs.python.org/3/library/typing.html),
[default arguments](https://docs.python.org/3/tutorial/controlflow.html#default-argument-values),
[exceptions](https://docs.python.org/3/tutorial/errors.html),
[context managers](https://docs.python.org/3/library/contextlib.html),
[asyncio tasks](https://docs.python.org/3/library/asyncio-task.html),
[unittest](https://docs.python.org/3/library/unittest.html).
