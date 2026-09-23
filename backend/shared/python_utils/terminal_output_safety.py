"""Bounded safety processing for untrusted terminal output.

Terminal output is treated as external text even when OpenMates selected the
command.  This module owns the deterministic cleanup and the exact server-side
receipt used before output can enter autonomous model context.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import re
from typing import Any, Literal

from backend.apps.ai.processing.external_result_sanitizer import (
    BOUNDARY_CONTEXT_CHARS,
    PROMPT_INJECTION_PLACEHOLDER,
)
from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling
from backend.shared.providers.e2b_code_runner import redact_execution_output
from backend.shared.python_utils.structured_content_sanitization import (
    MAX_BATCH_CHARS,
    MAX_UNIT_CHARS,
    SAFETY_ERROR_INVALID,
    SAFETY_ERROR_TIMEOUT,
    SAFETY_ERROR_TOO_LARGE,
    SAFETY_ERROR_UNAVAILABLE,
    StructuredScanError,
    TextDecision,
    classify_text_units,
    serialized_units_size,
)


TERMINAL_OUTPUT_SAFETY_POLICY = "terminal-output-v1"
TERMINAL_OUTPUT_MAX_MODEL_CHARS = 24_000
TERMINAL_OUTPUT_SCAN_TIMEOUT_SECONDS = 20.0
TERMINAL_OUTPUT_TRUNCATION_MARKER = "\n\n[... terminal output omitted from this selected excerpt ...]\n\n"
_KNOWN_SCAN_ERRORS = {
    SAFETY_ERROR_INVALID,
    SAFETY_ERROR_TIMEOUT,
    SAFETY_ERROR_TOO_LARGE,
    SAFETY_ERROR_UNAVAILABLE,
}

# ECMA-48 CSI, OSC, DCS/SOS/PM/APC and two-byte escape functions. Removing the
# complete sequence prevents the visible residue from being interpreted as a
# terminal action by a downstream renderer.
_TERMINAL_ESCAPE_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|[PX^_].*?(?:\x1b\\|$)"
    r"|\[[0-?]*[ -/]*[@-~]"
    r"|[@-_]"
    r")",
    re.DOTALL,
)
_UNICODE_TAG_RE = re.compile(r"[\U000E0000-\U000E007F]")


@dataclass(frozen=True)
class TerminalOutputSafetyReceipt:
    """Server-created record of exactly what terminal text was reviewed."""

    policy: str
    scan_status: Literal["scanned", "unscanned"]
    scan_reason: str | None
    coverage: Literal["full", "selected_excerpt"]
    input_chars: int
    normalized_chars: int
    selected_chars: int
    delivered_chars: int
    omitted_chars: int
    truncated: bool
    terminal_sequences_removed: int
    ascii_characters_removed: int
    unit_count: int
    safe_units: int
    injection_units: int
    injection_spans: int
    uncertain_units: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerminalOutputSafetyResult:
    """Model text is absent whenever semantic coverage was not established."""

    model_text: str | None
    receipt: TerminalOutputSafetyReceipt


def normalize_terminal_output(text: str) -> tuple[str, dict[str, int]]:
    """Redact common secrets and neutralize terminal/control actions."""

    value = text if isinstance(text, str) else str(text or "")
    redacted = redact_execution_output(value)
    without_escapes, escape_count = _TERMINAL_ESCAPE_RE.subn("", redacted)
    # The generic sanitizer logs decoded Unicode-tag payloads for security
    # monitoring. Terminal logs may contain private command output, so remove
    # those tags first and retain only their count in the receipt.
    without_tags, tag_count = _UNICODE_TAG_RE.subn("", without_escapes)
    normalized, ascii_stats = sanitize_text_for_ascii_smuggling(
        without_tags,
        log_prefix="[TerminalOutputSafety] ",
        include_stats=True,
    )
    return normalized, {
        "terminal_sequences_removed": escape_count,
        "ascii_characters_removed": tag_count + int(ascii_stats.get("removed_count", 0)),
    }


def _select_bounded_excerpt(text: str, max_chars: int) -> tuple[str, int, bool]:
    if max_chars < len(TERMINAL_OUTPUT_TRUNCATION_MARKER) + 2:
        raise ValueError("max_chars is too small for a bounded terminal excerpt")
    if len(text) <= max_chars:
        return text, 0, False

    available = max_chars - len(TERMINAL_OUTPUT_TRUNCATION_MARKER)
    head_chars = available // 2
    tail_chars = available - head_chars
    omitted = len(text) - head_chars - tail_chars
    return (
        text[:head_chars]
        + TERMINAL_OUTPUT_TRUNCATION_MARKER
        + text[-tail_chars:],
        omitted,
        True,
    )


def _split_terminal_units(text: str) -> list[dict[str, str]]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > MAX_UNIT_CHARS:
        boundary = remaining.rfind("\n\n", 0, MAX_UNIT_CHARS + 1)
        if boundary <= 0:
            boundary = max(
                remaining.rfind(". ", 0, MAX_UNIT_CHARS + 1),
                remaining.rfind("\n", 0, MAX_UNIT_CHARS + 1),
            )
        end = boundary + (2 if remaining[boundary : boundary + 2] == ". " else 0) if boundary > 0 else MAX_UNIT_CHARS
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    if remaining:
        chunks.append(remaining)

    return [
        {
            "id": f"terminal-unit-{index}",
            "path": "terminal_output",
            "text": chunk,
            "context_before": chunks[index - 1][-BOUNDARY_CONTEXT_CHARS:] if index else "",
            "context_after": chunks[index + 1][:BOUNDARY_CONTEXT_CHARS] if index + 1 < len(chunks) else "",
        }
        for index, chunk in enumerate(chunks)
    ]


def _redact_injection_spans(text: str, decision: TextDecision) -> str:
    if decision.verdict != "injection":
        return text
    merged: list[tuple[int, int]] = []
    for start, end in sorted(decision.spans):
        if not (0 <= start < end <= len(text)):
            raise StructuredScanError(SAFETY_ERROR_INVALID)
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    if not merged:
        raise StructuredScanError(SAFETY_ERROR_INVALID)
    for start, end in reversed(merged):
        text = text[:start] + PROMPT_INJECTION_PLACEHOLDER + text[end:]
    return text


async def sanitize_terminal_output_for_model(
    text: str,
    *,
    task_id: str,
    secrets_manager: Any = None,
    cache_service: Any = None,
    max_chars: int = TERMINAL_OUTPUT_MAX_MODEL_CHARS,
    timeout_seconds: float = TERMINAL_OUTPUT_SCAN_TIMEOUT_SECONDS,
) -> TerminalOutputSafetyResult:
    """Return one bounded, checked terminal excerpt and its exact receipt.

    Short strings are explicitly classified. Long transcripts are represented by
    a labelled head/tail excerpt split into bounded units with neighbor context.
    A technical scanner failure withholds text from autonomous model input.
    """

    raw = text if isinstance(text, str) else str(text or "")
    normalized, cleanup = normalize_terminal_output(raw)
    selected, omitted_chars, truncated = _select_bounded_excerpt(normalized, max_chars)
    coverage: Literal["full", "selected_excerpt"] = "selected_excerpt" if truncated else "full"
    units = _split_terminal_units(selected)

    base_receipt = {
        "policy": TERMINAL_OUTPUT_SAFETY_POLICY,
        "coverage": coverage,
        "input_chars": len(raw),
        "normalized_chars": len(normalized),
        "selected_chars": len(selected),
        "omitted_chars": omitted_chars,
        "truncated": truncated,
        **cleanup,
    }
    if not units:
        receipt = TerminalOutputSafetyReceipt(
            scan_status="scanned",
            scan_reason=None,
            delivered_chars=0,
            unit_count=0,
            safe_units=0,
            injection_units=0,
            injection_spans=0,
            uncertain_units=0,
            **base_receipt,
        )
        return TerminalOutputSafetyResult(model_text="", receipt=receipt)

    try:
        if serialized_units_size(units) > MAX_BATCH_CHARS:
            raise StructuredScanError(SAFETY_ERROR_TOO_LARGE)
        decisions = await asyncio.wait_for(
            classify_text_units(
                units,
                task_id=task_id,
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            ),
            timeout=timeout_seconds,
        )
        expected_ids = {unit["id"] for unit in units}
        if set(decisions) != expected_ids or any(
            not isinstance(decision, TextDecision)
            or decision.verdict not in {"safe", "injection", "uncertain"}
            for decision in decisions.values()
        ):
            raise StructuredScanError(SAFETY_ERROR_INVALID)
        delivered = "".join(
            _redact_injection_spans(unit["text"], decisions[unit["id"]])
            for unit in units
        )
        receipt = TerminalOutputSafetyReceipt(
            scan_status="scanned",
            scan_reason=None,
            delivered_chars=len(delivered),
            unit_count=len(units),
            safe_units=sum(decision.verdict == "safe" for decision in decisions.values()),
            injection_units=sum(decision.verdict == "injection" for decision in decisions.values()),
            injection_spans=sum(len(decision.spans) for decision in decisions.values()),
            uncertain_units=sum(decision.verdict == "uncertain" for decision in decisions.values()),
            **base_receipt,
        )
        return TerminalOutputSafetyResult(model_text=delivered, receipt=receipt)
    except asyncio.TimeoutError:
        reason = SAFETY_ERROR_TIMEOUT
    except Exception as exc:
        reason = str(exc) if str(exc) in _KNOWN_SCAN_ERRORS else SAFETY_ERROR_UNAVAILABLE

    receipt = TerminalOutputSafetyReceipt(
        scan_status="unscanned",
        scan_reason=reason,
        delivered_chars=0,
        unit_count=len(units),
        safe_units=0,
        injection_units=0,
        injection_spans=0,
        uncertain_units=0,
        **base_receipt,
    )
    return TerminalOutputSafetyResult(model_text=None, receipt=receipt)


def terminal_output_receipt_allows_model(
    receipt: Any,
    *,
    delivered_chars: int,
) -> bool:
    """Validate a server-cache receipt before reusing its checked output."""

    if not isinstance(receipt, dict):
        return False
    count_fields = (
        "input_chars",
        "normalized_chars",
        "selected_chars",
        "delivered_chars",
        "omitted_chars",
        "terminal_sequences_removed",
        "ascii_characters_removed",
        "unit_count",
        "safe_units",
        "injection_units",
        "injection_spans",
        "uncertain_units",
    )
    if any(type(receipt.get(field)) is not int or receipt[field] < 0 for field in count_fields):
        return False
    if (
        receipt.get("policy") != TERMINAL_OUTPUT_SAFETY_POLICY
        or receipt.get("scan_status") != "scanned"
        or receipt.get("scan_reason") is not None
        or type(receipt.get("truncated")) is not bool
        or receipt.get("coverage") not in {"full", "selected_excerpt"}
        or receipt["unit_count"]
        != receipt["safe_units"] + receipt["injection_units"] + receipt["uncertain_units"]
        or receipt["delivered_chars"] != delivered_chars
        or receipt["selected_chars"] > TERMINAL_OUTPUT_MAX_MODEL_CHARS
        or delivered_chars
        > TERMINAL_OUTPUT_MAX_MODEL_CHARS + len(PROMPT_INJECTION_PLACEHOLDER) * receipt["injection_spans"]
    ):
        return False
    if receipt["coverage"] == "full":
        return (
            receipt["truncated"] is False
            and receipt["omitted_chars"] == 0
            and receipt["selected_chars"] == receipt["normalized_chars"]
        )
    return (
        receipt["truncated"] is True
        and receipt["omitted_chars"] > 0
        and receipt["selected_chars"] == TERMINAL_OUTPUT_MAX_MODEL_CHARS
        and receipt["normalized_chars"]
        == receipt["selected_chars"] - len(TERMINAL_OUTPUT_TRUNCATION_MARKER) + receipt["omitted_chars"]
    )
