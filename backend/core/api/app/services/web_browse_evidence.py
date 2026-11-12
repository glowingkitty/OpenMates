"""Browse evidence ledger, literal quote checks and code matching of answer values.

The ledger is the run's memory across pages: `{url, title, notes:[{fact, quote}]}`
per page. A planner note enters it only when its quote occurs literally in the
page it was read from (or equals a link URL observed there). The answer check
then matches every string/number leaf of an extracted answer against those
quotes and the current page, and prunes what code cannot match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import math
import re
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator

from backend.shared.providers.browser_planner import bounded_ledger, document_excerpt

MAX_PAGES = 60
MAX_NOTES = 400
MAX_QUOTE = 600
MAX_FACT = 600
MIN_QUOTE = 3
_REMOVED = object()
_NUMBER = re.compile(r"\d(?:[\d.,'   ]*\d)?")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def page_text(observation: dict[str, Any]) -> str:
    return observation.get("document_text") or observation.get("text") or ""


def observed_urls(observation: dict[str, Any]) -> set[str]:
    urls = {observation.get("url", "")}
    for item in [*observation.get("links", []), *observation.get("controls", [])]:
        if isinstance(item, dict):
            urls.update(
                v for k in ("url", "href") if isinstance(v := item.get(k), str) and v
            )
    urls.discard("")
    return urls


def note_count(ledger: list[dict[str, Any]]) -> int:
    return sum(len(page["notes"]) for page in ledger)


@dataclass
class NoteOutcome:
    accepted: int = 0
    rejected: int = 0
    dropped: int = 0


def accept_notes(
    ledger: list[dict[str, Any]],
    observation: dict[str, Any],
    notes: list[dict[str, str]],
) -> NoteOutcome:
    """Append code-checked notes for the observation the planner read; mutates `ledger`."""
    outcome = NoteOutcome()
    text = normalize(page_text(observation))
    urls = observed_urls(observation)
    url = observation.get("url", "")
    entry = next((page for page in ledger if page["url"] == url), None)
    fresh = entry is None
    if fresh:
        entry = {"url": url, "title": observation.get("title", ""), "notes": []}
    known = {normalize(n["quote"]) for n in entry["notes"]}
    for note in notes:
        quote = " ".join(note["quote"].split())
        normalized = normalize(quote)
        if len(normalized) < MIN_QUOTE or (
            normalized not in text and quote not in urls
        ):
            outcome.rejected += 1
            continue
        if normalized in known:
            continue
        if note_count(ledger) + (len(entry["notes"]) if fresh else 0) >= MAX_NOTES or (
            fresh and len(ledger) >= MAX_PAGES
        ):
            outcome.dropped += 1
            continue
        # A literal prefix of an observed quotation is still observed text.
        entry["notes"].append(
            {"fact": note["fact"][:MAX_FACT], "quote": quote[:MAX_QUOTE]}
        )
        known.add(normalized)
        outcome.accepted += 1
    if fresh and entry["notes"]:
        ledger.append(entry)
    return outcome


def _digit_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _NUMBER.findall(text):
        for part in {match, *re.split(r"[\s  ]+", match)}:
            digits = re.sub(r"\D", "", part)
            if digits:
                tokens.add(digits.lstrip("0") or "0")
    return tokens


def _number_candidates(value: int | float) -> set[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return set()
    try:
        number = abs(Decimal(str(value)))
    except InvalidOperation:
        return set()
    if number == number.to_integral_value():
        whole = str(int(number))
        candidates = {whole, whole + "0", whole + "00"}
    else:
        candidates = {format(number, "f"), f"{number:.2f}"}
    return {re.sub(r"\D", "", c).lstrip("0") or "0" for c in candidates}


@dataclass
class _Source:
    url: str
    title: str
    text: str
    digits: set[str]
    urls: set[str]


def evidence_sources(
    ledger: list[dict[str, Any]], observation: dict[str, Any]
) -> list[_Source]:
    """Ledger pages (quotes only, never model-authored facts) plus the current page."""
    sources = [
        _Source(
            url=page["url"],
            title=page.get("title", ""),
            text=normalize("\n".join(n["quote"] for n in page["notes"])),
            digits=_digit_tokens("\n".join(n["quote"] for n in page["notes"])),
            urls={page["url"]} | {n["quote"] for n in page["notes"]},
        )
        for page in ledger
    ]
    sources.append(
        _Source(
            url=observation.get("url", ""),
            title=observation.get("title", ""),
            text=normalize(page_text(observation)),
            digits=_digit_tokens(page_text(observation)),
            urls=observed_urls(observation),
        )
    )
    return sources


@dataclass
class AnswerCheck:
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    pruned: Any = None
    contributing: list[int] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)


def _pointer(path: str, key: Any) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def check_answer(
    data: Any,
    schema: dict[str, Any],
    ledger: list[dict[str, Any]],
    observation: dict[str, Any],
) -> AnswerCheck:
    """Match every string/number leaf; build the pruned answer and its missing paths."""
    sources = evidence_sources(ledger, observation)
    check = AnswerCheck()
    contributing: set[int] = set()

    def leaf(value: Any) -> set[int]:
        if isinstance(value, str):
            stripped = value.strip()
            normalized = normalize(value)
            if not normalized:
                return set()
            return {
                i
                for i, s in enumerate(sources)
                if stripped in s.urls or normalized in s.text
            }
        candidates = _number_candidates(value)
        return {i for i, s in enumerate(sources) if candidates & s.digits}

    def visit(value: Any, node: Any, path: str) -> tuple[Any, int, list[str]]:
        node = node if isinstance(node, dict) else {}
        if isinstance(value, dict):
            properties = node.get("properties") or {}
            extra = node.get("additionalProperties")
            required = set(node.get("required") or [])
            out: dict[str, Any] = {}
            matched, removed = 0, []
            for key, child in value.items():
                child_path = _pointer(path, key)
                new, count, gone = visit(
                    child,
                    properties.get(key, extra if isinstance(extra, dict) else {}),
                    child_path,
                )
                matched += count
                removed += gone
                if new is _REMOVED:
                    if key in required:
                        out[key] = None
                else:
                    out[key] = new
            return out, matched, removed
        if isinstance(value, list):
            items = node.get("items")
            kept, matched, removed = [], 0, []
            for index, child in enumerate(value):
                child_path = _pointer(path, index)
                new, count, gone = visit(child, items, child_path)
                if new is _REMOVED or (count == 0 and gone):
                    removed.append(child_path)
                    continue
                kept.append(new)
                matched += count
                removed += gone
            return kept, matched, removed
        if isinstance(value, bool) or value is None:
            return value, 0, []
        if isinstance(value, (str, int, float)):
            found = leaf(value)
            if found:
                contributing.update(found)
                return value, 1, []
            check.unmatched.append(path)
            return _REMOVED, 0, [path]
        return value, 0, []

    pruned, check.matched, check.missing = visit(data, schema, "")
    check.pruned = None if pruned is _REMOVED else pruned
    check.contributing = sorted(contributing)
    seen: set[str] = set()
    for i in check.contributing:
        if sources[i].url and sources[i].url not in seen:
            seen.add(sources[i].url)
            check.sources.append({"url": sources[i].url, "title": sources[i].title})
    return check


def partial_answer(check: AnswerCheck, schema: dict[str, Any]) -> bool:
    """A pruned answer qualifies when something matched remains and it validates."""
    return (
        bool(check.unmatched)
        and check.matched > 0
        and Draft202012Validator(schema).is_valid(check.pruned)
    )


def extraction_context(
    *,
    task: str,
    schema: dict[str, Any],
    ledger: list[dict[str, Any]],
    observation: dict[str, Any],
    private_account: bool,
    limit: int = 48_000,
) -> dict[str, Any]:
    """Goal, schema, the bounded ledger and as much of the current page as fits."""
    page: dict[str, Any] = {
        "url": observation.get("url", ""),
        "title": observation.get("title", ""),
        "tables": observation.get("tables") or [],
        "links": (observation.get("links") or [])[:100],
        "text": "",
    }
    context = {
        "purpose": "extract",
        "goal": task,
        "output_schema": schema,
        "private_account": private_account,
        "evidence": bounded_ledger(ledger, 20_000),
        "observed_page": page,
    }
    for optional in ("links", "tables"):
        if len(json.dumps(context, ensure_ascii=False)) <= limit - 4_000:
            break
        page[optional] = []
    budget = limit - len(json.dumps(context, ensure_ascii=False))
    page["text"] = document_excerpt(observation, budget)
    return context
