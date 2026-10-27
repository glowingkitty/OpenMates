"""Code-owned strict output scanning for paid autonomous operations.

The caller supplies an accounting-aware typed decision evaluator. Request bodies
cannot opt into, replace, or disable this context. Other callers keep their
existing output-safety behavior.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

DecisionEvaluator = Callable[..., Awaitable[Any]]
active_strict_scanner: ContextVar[DecisionEvaluator | None] = ContextVar(
    "active_strict_scanner", default=None
)


class StrictSafetyUnavailable(RuntimeError):
    pass


@contextmanager
def strict_output_safety(evaluate: DecisionEvaluator):
    token = active_strict_scanner.set(evaluate)
    try:
        yield
    finally:
        active_strict_scanner.reset(token)
