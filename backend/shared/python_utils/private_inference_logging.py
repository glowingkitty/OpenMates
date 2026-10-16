"""Opt-in content-free logging for transient private voice inference.

The context propagates into nested asyncio tasks. Handler filters also cover
third-party SDK and skill loggers, so their exception strings cannot bypass the
provider-facing logging flag. Other requests retain their normal diagnostics.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import json
from typing import Iterator

_active: ContextVar[bool] = ContextVar("private_voice_inference_logging", default=False)
_STANDARD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
_IDENTITY_FIELDS = frozenset({"operation_id", "call_id", "function_call_id", "chat_id"})


def redact_private_record(record: logging.LogRecord) -> bool:
    """Retain the logger/event category and safe operation identities only."""
    if not _active.get():
        return False
    cost = None
    if record.name in {"backend.shared.providers.typesafe.client", "backend.apps.ai.processing.summary_billing"}:
        message = record.getMessage()
        prefix, _, raw = message.partition(" ")
        if prefix in {"LLM_JEV_COST", "LLM_SUMMARY_COST"}:
            try:
                value = json.loads(raw)
                allowed = {"task_id", "charge_id", "attempt_id", "purpose", "inference_host", "host", "model_id",
                    "http_status", "success", "input_tokens", "output_tokens", "reasoning_tokens",
                    "supplier_cost_usd", "supplier_cost_complete", "supplier_cost_source",
                    "supplier_cost_upper_bound_usd"}
                if isinstance(value, dict) and set(value).issubset(allowed):
                    cost = prefix + " " + json.dumps(value, sort_keys=True)
            except (TypeError, ValueError):
                pass
    record.msg = cost or f"Private voice operation event logger={record.name} level={record.levelname}"
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    for field in tuple(record.__dict__):
        if field not in _STANDARD_FIELDS and field not in _IDENTITY_FIELDS:
            del record.__dict__[field]
    return True


class _PrivateFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        redact_private_record(record)
        return True


def _install_handler_filters() -> None:
    loggers = [logging.getLogger(), *(value for value in logging.Logger.manager.loggerDict.values()
                                     if isinstance(value, logging.Logger))]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(value, _PrivateFilter) for value in handler.filters):
                handler.addFilter(_PrivateFilter())


@contextmanager
def private_inference_logging() -> Iterator[None]:
    """Scope redaction to one private operation across API and worker handlers."""
    _install_handler_filters()
    token = _active.set(True)
    try:
        yield
    finally:
        _active.reset(token)
