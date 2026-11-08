"""Pure-Python BM25 ranking of PDF pages for pdf.search.

Pages are tokenised on unicode word characters (lower-cased). Tokens that carry
inner punctuation (part numbers such as ``ATMEGA328P-PU`` or ``0x2F``, versions,
paths) are additionally indexed as a whole, so exact short strings still match.
An exact-phrase hit adds a small bonus, and a plain case-insensitive substring
hit is a score floor, so a literal occurrence is never dropped by tokenisation.

Spec: pdf-processing.search.ranked-pages
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping

BM25_K1 = 1.5
BM25_B = 0.75
PHRASE_BONUS = 1.0
SUBSTRING_FLOOR = 0.01

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_CHUNK_RE = re.compile(r"\S+")
_EDGE_PUNCT = ".,;:!?\"'()[]{}<>*_`|/\\-–—…"


def tokenize(text: str) -> List[str]:
    """Return lower-case word tokens plus punctuation-joined whole tokens."""
    lowered = text.lower()
    tokens = _WORD_RE.findall(lowered)
    for chunk in _CHUNK_RE.findall(lowered):
        stripped = chunk.strip(_EDGE_PUNCT)
        if stripped and not stripped.isalnum() and len(_WORD_RE.findall(stripped)) > 1:
            tokens.append(stripped)
    return tokens


@dataclass(frozen=True)
class RankedPage:
    """One page that matched the query, best first."""

    page_num: int
    score: float
    match_offset: int
    match_length: int


def _best_offset(text_lower: str, query_lower: str, query_tokens: Iterable[str], idf: Mapping[str, float]) -> tuple[int, int]:
    """Locate the most informative literal occurrence: the phrase, else the rarest query token."""
    idx = text_lower.find(query_lower)
    if idx != -1:
        return idx, len(query_lower)
    for token in sorted(set(query_tokens), key=lambda t: (-idf.get(t, 0.0), -len(t))):
        idx = text_lower.find(token)
        if idx != -1:
            return idx, len(token)
    return 0, 0


def rank_pages(pages: Mapping[int, str], query: str) -> List[RankedPage]:
    """Rank ``pages`` (page number -> text) against ``query`` with BM25.

    Only pages with a token or substring hit are returned, ordered by score
    (descending), then page number.
    """
    query_lower = query.lower().strip()
    if not query_lower or not pages:
        return []
    query_tokens = list(dict.fromkeys(tokenize(query_lower)))

    lowered: Dict[int, str] = {n: t.lower() for n, t in pages.items()}
    page_terms: Dict[int, Counter[str]] = {n: Counter(tokenize(t)) for n, t in pages.items()}
    lengths = {n: sum(terms.values()) for n, terms in page_terms.items()}
    doc_count = len(pages)
    avg_len = (sum(lengths.values()) / doc_count) or 1.0

    idf: Dict[str, float] = {}
    for token in query_tokens:
        containing = sum(1 for terms in page_terms.values() if token in terms)
        idf[token] = math.log(1.0 + (doc_count - containing + 0.5) / (containing + 0.5))

    multi_word = len(_WORD_RE.findall(query_lower)) > 1
    ranked: List[RankedPage] = []
    for page_num, terms in page_terms.items():
        norm = 1.0 - BM25_B + BM25_B * (lengths[page_num] / avg_len)
        score = 0.0
        for token in query_tokens:
            freq = terms.get(token, 0)
            if freq:
                score += idf[token] * (freq * (BM25_K1 + 1.0)) / (freq + BM25_K1 * norm)
        substring_hit = query_lower in lowered[page_num]
        if substring_hit:
            score = max(score, SUBSTRING_FLOOR)
            if multi_word:
                score += PHRASE_BONUS
        if score <= 0.0:
            continue
        offset, length = _best_offset(lowered[page_num], query_lower, query_tokens, idf)
        ranked.append(RankedPage(page_num, score, offset, length))

    ranked.sort(key=lambda r: (-r.score, r.page_num))
    return ranked
