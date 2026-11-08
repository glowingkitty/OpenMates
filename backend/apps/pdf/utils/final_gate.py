"""Finality gate and page-label helpers shared by the pdf.search and pdf.read skills.

The assistant turn is held until PDF processing is final, so a skill that still
sees an unfinished embed must fail instead of waiting or returning partial text.

Spec: pdf-processing.readiness.complete-before-answer
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

from backend.shared.python_utils.pdf_ocr_readiness import (
    PdfNotReadyError,
    PdfProcessingFailedError,
)

WHOLE_DOCUMENT_TOKEN_LIMIT = 30_000
LABEL_TRUSTED = "trusted"
LABEL_UNTRUSTED = "untrusted"
LABEL_UNCHECKED = "unchecked"


def require_final_pdf(content: Dict[str, Any], required_fields: Sequence[str]) -> Dict[str, Any]:
    """Return ``content`` only when processing is final; never allow partial content.

    Raises:
        PdfProcessingFailedError: the embed carries status "error".
        PdfNotReadyError: a required artefact is missing or the status is not "finished".
    """
    if content.get("status") == "error":
        raise PdfProcessingFailedError(
            content.get("error") or "PDF processing failed. Please upload the PDF again."
        )
    status = content.get("status")
    if any(not content.get(field) for field in required_fields) or (status is not None and status != "finished"):
        page_count = content.get("page_count")
        pages = f" ({page_count} pages)" if page_count else ""
        raise PdfNotReadyError(
            f"The PDF{pages} has not finished processing, so its content cannot be read yet. "
            "Tell the user it is not ready and to ask again shortly."
        )
    return content


def injection_label(page: Dict[str, Any]) -> str:
    """Return the page's injection label; missing or unknown values count as unchecked."""
    injection = page.get("injection")
    label = injection.get("label") if isinstance(injection, dict) else None
    return label if label in (LABEL_TRUSTED, LABEL_UNTRUSTED) else LABEL_UNCHECKED


def is_unreadable(page: Dict[str, Any]) -> bool:
    return page.get("unreadable") is True
