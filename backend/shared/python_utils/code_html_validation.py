# backend/shared/python_utils/code_html_validation.py
#
# Deterministic validation for generated standalone HTML returned by the Code
# image-to-HTML skill. The model output is user-visible code and later rendered
# in isolated E2B sandboxes, so this module keeps the contract intentionally
# narrow: one self-contained HTML document with inline CSS and optional inline JS.
# It does not attempt to sanitize arbitrary web content; it rejects unsupported
# references so callers can repair or fail visibly before embed creation.

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser


EXTERNAL_URL_PATTERN = re.compile(r"(?i)(?:https?:)?//")
CSS_URL_PATTERN = re.compile(r"(?is)url\(\s*(['\"]?)([^)'\"]+)\1\s*\)")
LOCAL_ASSETS_PATTERN = re.compile(r"(?i)(?:^|[\"'(/])local-assets(?:/|[\"')])")
MAX_REPAIR_PROMPT_CHARS = 900


@dataclass(frozen=True)
class InlineHtmlValidationResult:
    passed: bool
    errors: list[str]

    def to_repair_prompt(self) -> str:
        """Return bounded, URL-free instructions safe to send back to a model."""
        if self.passed:
            return "The HTML passed inline-only validation."

        sanitized_errors = [_redact_url(error) for error in self.errors]
        summary = (
            "Repair the generated HTML so it is a single self-contained index.html. "
            "Use only inline CSS and optional inline JavaScript. Validation errors: "
            + "; ".join(sanitized_errors)
        )
        return summary[:MAX_REPAIR_PROMPT_CHARS]


class _InlineHtmlReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}

        if normalized_tag == "script" and attr_map.get("src"):
            self.errors.append("external script references are not allowed")

        if normalized_tag == "img" and _is_external_or_local_asset(attr_map.get("src", "")):
            self.errors.append("external image references are not allowed")

        if normalized_tag == "link" and _is_external_or_local_asset(attr_map.get("href", "")):
            self.errors.append("external URL references are not allowed")

        for name, value in attr_map.items():
            if name in {"src", "href"}:
                continue
            if _is_external_or_local_asset(value):
                self.errors.append("external URL references are not allowed")

        style = attr_map.get("style")
        if style and _contains_external_or_local_asset_url(style):
            self.errors.append("external URL references are not allowed")

    def handle_data(self, data: str) -> None:
        if _contains_external_or_local_asset_url(data):
            self.errors.append("external URL references are not allowed")


def validate_inline_html(html: str) -> InlineHtmlValidationResult:
    """Validate generated HTML for the v1 inline-only output contract."""
    errors: list[str] = []
    if not html or not html.strip():
        errors.append("HTML content is required")

    if LOCAL_ASSETS_PATTERN.search(html):
        errors.append("local-assets references are not allowed")

    parser = _InlineHtmlReferenceParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        errors.append("HTML could not be parsed")
    errors.extend(parser.errors)

    for url_value in CSS_URL_PATTERN.findall(html):
        if _is_external_or_local_asset(url_value[1]):
            errors.append("external URL references are not allowed")

    deduped_errors = list(dict.fromkeys(errors))
    return InlineHtmlValidationResult(passed=not deduped_errors, errors=deduped_errors)


def _contains_external_or_local_asset_url(value: str) -> bool:
    if _is_external_or_local_asset(value):
        return True
    return any(_is_external_or_local_asset(match[1]) for match in CSS_URL_PATTERN.findall(value))


def _is_external_or_local_asset(value: str) -> bool:
    stripped = value.strip()
    if stripped.lower().startswith("data:"):
        return False
    stripped = _strip_data_urls(stripped)
    return bool(EXTERNAL_URL_PATTERN.search(stripped) or LOCAL_ASSETS_PATTERN.search(stripped))


def _strip_data_urls(value: str) -> str:
    return re.sub(r"(?is)data:[^\s;\"')]+(?:;[^\s,\"')]+)*,[^\s\"')]+", "<data-url>", value)


def _redact_url(value: str) -> str:
    redacted = re.sub(r"(?i)https?://[^\s;\"')]+", "<external URL>", value)
    return re.sub(r"(?i)//[^\s;\"')]+", "<external URL>", redacted)
