# backend/shared/providers/gmail/mime.py
#
# Pure MIME helpers for the Gmail provider: decoding message payloads into
# readable text (text/plain preferred, HTML stripped) and building RFC 5322
# draft messages. Placeholder tokens that were never resolved to real values
# are rejected here so they can never reach Google.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any

from .errors import MailInputError

MAX_BODY_CHARS = 20000
MAX_RECIPIENTS = 50
# Client-side privacy placeholders such as [EMAIL_1_org] or [PHONE_567]; also template braces.
_PLACEHOLDER_RE = re.compile(r"\[(?:EMAIL|PHONE|CARD|NAME|ADDRESS|IBAN|[A-Z]{3,12})_\d+[A-Za-z0-9_]*\]|\{\{[^}]{1,60}\}\}")
_ADDRESS_RE = re.compile(r"^[^@\s<>\[\]{},;]+@[^@\s<>\[\]{},;]+\.[^@\s<>\[\]{},;]+$")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _walk(part: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [part]
    for child in part.get("parts") or []:
        parts.extend(_walk(child))
    return parts


def extract_body(payload: dict[str, Any]) -> str:
    """Readable body: text/plain parts preferred, otherwise HTML stripped of markup."""

    plain: list[str] = []
    html: list[str] = []
    for part in _walk(payload):
        data = (part.get("body") or {}).get("data")
        if not data or part.get("filename"):
            continue
        mime_type = str(part.get("mimeType", ""))
        if mime_type == "text/plain":
            plain.append(_decode(data))
        elif mime_type == "text/html":
            html.append(html_to_text(_decode(data)))
    text = "\n\n".join(plain) if plain else "\n\n".join(html)
    return text.strip()[:MAX_BODY_CHARS]


def header_map(payload: dict[str, Any]) -> dict[str, str]:
    return {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in payload.get("headers") or []}


def attachment_names(payload: dict[str, Any]) -> list[str]:
    return [str(p["filename"]) for p in _walk(payload) if p.get("filename")]


def reject_placeholders(value: str, field: str) -> None:
    if _PLACEHOLDER_RE.search(value):
        raise MailInputError(
            "unresolved_placeholder",
            f"{field} still contains an unresolved privacy placeholder; nothing was sent to Google. "
            "Ask the user for the real value.",
        )


def normalize_recipients(values: list[str] | None, field: str) -> list[str]:
    cleaned: list[str] = []
    for raw in values or []:
        reject_placeholders(raw, field)
        for _name, address in getaddresses([raw]):
            if not _ADDRESS_RE.match(address) or "\n" in raw or "\r" in raw:
                raise MailInputError("invalid_recipient", f"{field} contains an invalid email address.")
            cleaned.append(address)
    if len(cleaned) > MAX_RECIPIENTS:
        raise MailInputError("too_many_recipients", f"At most {MAX_RECIPIENTS} recipients per field.")
    return cleaned


def build_draft_raw(
    *, to: list[str], cc: list[str], bcc: list[str], subject: str, body: str,
    in_reply_to: str | None = None, references: str | None = None,
) -> str:
    """Return the base64url RFC 5322 message for drafts.create (never sent by this code)."""

    reject_placeholders(subject, "subject")
    reject_placeholders(body, "body")
    if "\n" in subject or "\r" in subject:
        raise MailInputError("invalid_subject", "subject must be a single line.")
    message = EmailMessage()
    if to:
        message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
