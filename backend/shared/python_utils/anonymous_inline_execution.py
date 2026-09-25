"""Request-local context for anonymous skills that must finish inline."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_active: ContextVar[bool] = ContextVar("anonymous_inline_execution", default=False)


@contextmanager
def anonymous_inline_execution(enabled: bool = True) -> Iterator[None]:
    token = _active.set(enabled)
    try:
        yield
    finally:
        _active.reset(token)


def is_anonymous_inline_execution() -> bool:
    return _active.get()
