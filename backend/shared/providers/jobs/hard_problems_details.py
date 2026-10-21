"""Bounded, source-verified details from Hard Problems' public role pages."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any

import httpx

from .common import ProviderError, clean_text, normalize_employment_type, safe_url

MAX_DETAIL_BYTES = 256_000
MAX_DESCRIPTION_CHARS = 20_000
FACT_FIELDS = {
    "Sector": "sector", "Role": "role", "Seniority": "seniority",
    "Organisation": "organization_type", "On-site or remote": "work_arrangement",
    "Salary": "salary_text",
}


class _RoleParser(HTMLParser):
    """Read JSON-LD and the job's definition list, excluding navigation/scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.facts: dict[str, str] = {}
        self._script: list[str] | None = None
        self._main = False
        self._dl = False
        self._cell: str | None = None
        self._parts: list[str] = []
        self._label = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._script = []
        elif tag == "main":
            self._main = True
        elif tag == "dl" and self._main:
            self._dl = True
        elif tag in {"dt", "dd"} and self._dl:
            self._cell, self._parts = tag, []

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        elif self._cell:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
        elif tag == self._cell:
            value = clean_text(" ".join(self._parts), max_length=300)
            if tag == "dt":
                self._label = value
            elif self._label in FACT_FIELDS and value.casefold() not in {"n/a", "na", "not specified"}:
                self.facts[FACT_FIELDS[self._label]] = value
            self._cell = None
        elif tag == "dl":
            self._dl = False
        elif tag == "main":
            self._main = False


def _postings(value: Any):
    if isinstance(value, list):
        for child in value:
            yield from _postings(child)
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
            yield value
        yield from _postings(value.get("@graph"))


def parse_role_details(html: str, source_url: str) -> dict[str, str]:
    """Keep only the matching posting; all returned prose is inert plain text."""
    parser = _RoleParser()
    parser.feed(html)
    for script in parser.scripts:
        try:
            payload = json.loads(script)
        except (ValueError, RecursionError):
            continue
        for posting in _postings(payload):
            if safe_url(posting.get("url")) != source_url:
                continue
            result = dict(parser.facts)
            description = posting.get("description")
            if isinstance(description, str):
                paragraphs = [clean_text(re.sub(r"^#{1,6}\s+", "", line.strip()),
                                         max_length=MAX_DESCRIPTION_CHARS)
                              for line in description.splitlines()]
                body = "\n\n".join(part for part in paragraphs if part)[:MAX_DESCRIPTION_CHARS]
                if body:
                    result["description"] = body
            employment = normalize_employment_type(posting.get("employmentType"))
            if employment:
                result["employment_type"] = employment
            deadline = posting.get("validThrough")
            if isinstance(deadline, str) and len(deadline) <= 80:
                result["valid_through"] = deadline
            if not result.get("description"):
                raise ProviderError("invalid_response", "Additional job details could not be read.")
            result["detail_status"] = "complete"
            return result
    raise ProviderError("invalid_response", "Additional job details could not be read.")


async def fetch_role_details(client: httpx.AsyncClient, source_url: str) -> dict[str, str]:
    """Never follow redirects or fetch employer/other arbitrary feed targets."""
    checked = safe_url(source_url, allowed_hosts={"www.hardproblems.com", "hardproblems.com"})
    if not checked or not httpx.URL(checked).path.startswith("/jobs/role/"):
        raise ProviderError("invalid_response", "Job detail URL is not a Hard Problems role page.")
    try:
        async with client.stream("GET", checked, follow_redirects=False) as response:
            if response.status_code != 200:
                raise ProviderError("unavailable", "Additional job details are temporarily unavailable.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_DETAIL_BYTES:
                    raise ProviderError("invalid_response", "Job detail page exceeded its bounded size.")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderError("unavailable", "Additional job details are temporarily unavailable.") from exc
    return parse_role_details(body.decode("utf-8", errors="replace"), checked)
