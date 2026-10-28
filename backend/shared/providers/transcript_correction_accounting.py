"""Optional request-local admission for ephemeral transcript provider attempts.

Provider wrappers remain independent of API/billing services. A caller may bind
an accountant; child correction tasks inherit it without changing signed-in calls.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any


class CorrectionAccountingError(RuntimeError):
    """Admission/settlement failure must stop provider fallback dispatch."""


correction_accountant: ContextVar[Any] = ContextVar(
    "correction_accountant", default=None
)
GUEST_CORRECTION_OUTPUT_TOKENS = 2048
logger = logging.getLogger(__name__)


def correction_output_limit(default: int) -> int:
    return (
        min(default, GUEST_CORRECTION_OUTPUT_TOKENS)
        if correction_accountant.get()
        else default
    )


@asynccontextmanager
async def admitted_correction(model: str, input_bytes: int, output_tokens: int):
    accountant = correction_accountant.get()
    try:
        operation = (
            await accountant.reserve_correction(model, input_bytes, output_tokens)
            if accountant
            else None
        )
    except Exception as exc:
        raise CorrectionAccountingError(
            "Transcript correction admission unavailable"
        ) from exc
    try:
        yield operation
    except BaseException:
        # Finalize ambiguous dispatched work at its admitted cap, before the
        # generic pending-reservation expiry can refund it. Preserve the original
        # provider failure or cancellation so established fallback still works.
        if operation is not None:
            try:
                await asyncio.shield(operation.finalize_unresolved())
            except BaseException:
                logger.warning(
                    "Guest correction terminal accounting failed"
                )
        raise
    else:
        if operation is not None:
            try:
                await operation.finalize_unresolved()
            except Exception as exc:
                raise CorrectionAccountingError(
                    "Transcript correction terminal settlement unavailable"
                ) from exc


async def settle_correction(
    operation: Any, input_tokens: Any, output_tokens: Any
) -> None:
    if operation is not None:
        try:
            await operation.settle(input_tokens, output_tokens)
        except Exception as exc:
            raise CorrectionAccountingError(
                "Transcript correction settlement unavailable"
            ) from exc


def mark_correction_dispatched(operation: Any) -> None:
    if operation is not None:
        operation.mark_dispatched()


class _CorrectionDispatchTransport(httpx.AsyncBaseTransport):
    """Mark the attempt after HTTP client setup, directly before network IO."""

    def __init__(self, operation: Any) -> None:
        self.operation = operation
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        mark_correction_dispatched(self.operation)
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self.transport.aclose()


def correction_dispatch_transport(operation: Any) -> httpx.AsyncBaseTransport | None:
    return _CorrectionDispatchTransport(operation) if operation is not None else None
