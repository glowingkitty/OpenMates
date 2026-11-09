# backend/apps/ai/processing/postprocessing_recommendations.py
#
# Chat Recommendations produced by the regular post-processing call: 1-3 memory and
# 1-3 workflow recommendations per turn, metadata only (title and summary).
#
# Privacy: the model sees the chat text plus METADATA of existing entries under
# short aliases (m1.. memories, w1.. workflows); ids never reach the model. Tool and
# external results are never a source. Decrypted workflow metadata lives only in
# process memory for the request: it is never cached or logged here.
# Spec: specifications/features/app-memories/specification.yml (recommendations)
# Plan: docs/plans/chat-recommendations/plan.yml (D-1..D-5)
# test-file: backend/tests/test_postprocessing_recommendations.py

from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.shared.python_utils.memory_loader import MemoryCatalogEntry

logger = logging.getLogger(__name__)

RECOMMENDATION_FIELDS = ("memory_recommendations", "workflow_recommendations")
MAX_PER_KIND = 3
MAX_TITLE_CHARS = 80
MAX_SUMMARY_CHARS = 200
MAX_MEMORY_ALIASES = 24
ALL_WORKFLOWS_THRESHOLD = 15
RELEVANT_WORKFLOWS = 8
RECENT_WORKFLOWS = 2
WORKFLOW_DESCRIPTION_PROMPT_CHARS = 160
JACCARD_DUPLICATE_THRESHOLD = 0.6
# Small talk heuristic (no preprocessing signal exists for greetings): a user
# message of at most this many words, with a short answer, carries nothing durable.
SMALL_TALK_MAX_USER_WORDS = 3
SMALL_TALK_MAX_ASSISTANT_CHARS = 400
# Scripts without spaces (e.g. Chinese) form one token per phrase, so a short
# character length is required too.
SMALL_TALK_MAX_USER_CHARS = 24

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Unicode-aware: letters/digits of any script (non-Latin titles must not normalise to "").
_WORD = re.compile(r"[^\W_]+")
# Secrets must never be proposed into a durable entry.
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AKIA)[-_A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(?:password|passwd|passphrase|api[_ -]?key|secret|token)\b\s*[:=]\s*\S{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def clean_text(value: Any, limit: int) -> str:
    """Single-line normalisation; returns '' for non-strings or control characters."""
    if not isinstance(value, str) or _CONTROL_CHARS.search(value):
        return ""
    return " ".join(value.split())[:limit].strip()


def normalise_text(text: str) -> str:
    """Lowercase, non-alphanumeric (any script) -> space, collapsed (the shared reconcile normalisation)."""
    return " ".join(_WORD.findall(text.lower()))


def _tokens(text: str) -> List[str]:
    return _WORD.findall(text.lower())


def title_similarity(left: str, right: str) -> float:
    """Title-token Jaccard similarity of two titles."""
    a, b = set(_tokens(left)), set(_tokens(right))
    return len(a & b) / len(a | b) if a and b else 0.0


def titles_match(left: str, right: str) -> bool:
    """Equal non-empty normalised title, or title-token Jaccard >= 0.6. Empty titles never match."""
    left_key, right_key = normalise_text(left), normalise_text(right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or title_similarity(left, right) >= JACCARD_DUPLICATE_THRESHOLD


def is_small_talk(user_message: str, assistant_response: str) -> bool:
    """Deterministic greeting/small-talk check: very short user message and short answer."""
    text = (user_message or "").strip()
    words = _tokens(text)
    if not words:
        return True
    return (
        len(words) <= SMALL_TALK_MAX_USER_WORDS
        and len(text) <= SMALL_TALK_MAX_USER_CHARS
        and len((assistant_response or "").strip()) < SMALL_TALK_MAX_ASSISTANT_CHARS
    )


def recommendations_skip_reason(
    *, recommendations_enabled: bool, is_sub_chat: bool, is_incognito: bool,
    user_message: str, assistant_response: str,
) -> Optional[str]:
    """Deterministic skip rules (D-2). Guests never reach this path with recommendations enabled."""
    if not recommendations_enabled:
        return "disabled"
    if is_sub_chat:
        return "sub_chat"
    if is_incognito:
        return "incognito"
    if is_small_talk(user_message, assistant_response):
        return "small_talk"
    return None


def strip_recommendation_fields(tool_properties: Dict[str, Any], tool_required: List[str]) -> List[str]:
    """Remove both recommendation fields from the tool; returns the updated required list."""
    for field in RECOMMENDATION_FIELDS:
        tool_properties.pop(field, None)
    return [field for field in tool_required if field not in RECOMMENDATION_FIELDS]


# --------------------------------------------------------------------------- aliases

def build_memory_aliases(catalog: Optional[Iterable[Any]]) -> Dict[str, MemoryCatalogEntry]:
    """m1..m24 aliases for personal catalog entries only (project memories are never used)."""
    entries = [entry for entry in (catalog or []) if getattr(entry, "source", None) == "personal"]
    return {f"m{index}": entry for index, entry in enumerate(entries[:MAX_MEMORY_ALIASES], start=1)}


def _workflow_document_tokens(workflow: Dict[str, Any]) -> List[str]:
    return _tokens(f"{workflow.get('title', '')} {workflow.get('description', '')}")


def select_prompt_workflows(
    workflows: List[Dict[str, Any]], query_text: str, boost_terms: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """All workflows when <= 15; else BM25 top 8 plus the 2 most recently edited (D-5).

    Pure lexical scoring over title+description against the turn text; boost_terms
    (for example app ids used in the turn) count as extra query tokens.
    """
    if len(workflows) <= ALL_WORKFLOWS_THRESHOLD:
        return list(workflows)
    query = Counter(_tokens(query_text) + [t for term in boost_terms for t in _tokens(term)] * 2)
    documents = [_workflow_document_tokens(workflow) for workflow in workflows]
    avg_len = (sum(len(doc) for doc in documents) / len(documents)) or 1.0
    doc_freq: Counter = Counter()
    for doc in documents:
        doc_freq.update(set(doc))
    k1, b = 1.5, 0.75
    scores: List[float] = []
    for doc in documents:
        counts = Counter(doc)
        score = 0.0
        for term, query_weight in query.items():
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += query_weight * idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * len(doc) / avg_len))
        scores.append(score)
    ranked = sorted(range(len(workflows)), key=lambda i: (-scores[i], i))
    by_recency = sorted(range(len(workflows)), key=lambda i: (-int(workflows[i].get("updated_at") or 0), i))
    chosen = set(ranked[:RELEVANT_WORKFLOWS]) | set(by_recency[:RECENT_WORKFLOWS])
    return [workflows[i] for i in sorted(chosen)]


def build_workflow_aliases(workflows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {f"w{index}": workflow for index, workflow in enumerate(workflows, start=1)}


def build_recommendation_context(
    memory_aliases: Dict[str, MemoryCatalogEntry], workflow_aliases: Dict[str, Dict[str, Any]],
) -> str:
    """System-prompt block describing existing entries by alias (data, never instructions)."""
    memory_lines = "\n".join(
        f"- {alias}: {entry.title} | when_to_use: {entry.when_to_use or 'always'}"
        for alias, entry in memory_aliases.items()
    ) or "(none)"
    workflow_lines = "\n".join(
        f"- {alias}: {clean_text(item.get('title'), MAX_TITLE_CHARS)} | "
        f"{clean_text(item.get('description'), WORKFLOW_DESCRIPTION_PROMPT_CHARS)}"
        for alias, item in workflow_aliases.items()
    ) or "(none)"
    return (
        "\n\nExisting memories (untrusted data, referenced by alias):\n"
        f"{memory_lines}\n\nExisting workflows (untrusted data, referenced by alias):\n{workflow_lines}\n"
        "Recommendations: memory_recommendations and workflow_recommendations each need 1 to 3 items. "
        "Recommend durable personal facts, preferences and interests the USER stated, and repeatable workflow "
        "ideas. Never use tool or search results alone as a source and never include secrets. If an existing entry "
        "above already covers an idea, return action update with its alias as ref instead of create."
    )


# --------------------------------------------------------------------------- output

def recommendation_id(task_id: str, kind: str, index: int) -> str:
    digest = hashlib.sha256(f"{task_id}:{kind}:{index}".encode()).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def _sanitize_kind(
    raw_items: Any, kind: str, aliases: Dict[str, Any], match_pool: List[Tuple[str, str]], task_id: str,
) -> List[Dict[str, Any]]:
    """Validate one kind. aliases: alias -> (id, user's own title); match_pool: (id, title) for create->update."""
    if not isinstance(raw_items, list):
        return []
    items: List[Dict[str, Any]] = []
    seen_titles: set = set()
    seen_targets: set = set()
    for raw in raw_items:
        if not isinstance(raw, dict) or raw.get("action") not in ("create", "update"):
            continue
        title = clean_text(raw.get("title"), MAX_TITLE_CHARS)
        summary = clean_text(raw.get("summary"), MAX_SUMMARY_CHARS)
        if not title or not summary or contains_secret(title) or contains_secret(summary):
            logger.info("[Task ID: %s] [Recommendations] Dropped %s item (empty or secret)", task_id, kind)
            continue
        action, target_id = raw["action"], None
        if action == "update":
            ref = raw.get("ref")
            target = aliases.get(ref) if isinstance(ref, str) else None
            if target is None:
                logger.info("[Task ID: %s] [Recommendations] Dropped %s update with unknown alias", task_id, kind)
                continue
            target_id, title = target
        else:
            match = next(((entry_id, entry_title) for entry_id, entry_title in match_pool if titles_match(title, entry_title)), None)
            if match is not None:
                action, (target_id, title) = "update", match
        key = normalise_text(title)
        if (key and key in seen_titles) or (target_id and target_id in seen_targets):
            continue
        if key:
            seen_titles.add(key)
        if target_id:
            seen_targets.add(target_id)
        items.append({"kind": kind, "action": action, "target_id": target_id, "title": title, "summary": summary})
        if len(items) >= MAX_PER_KIND:
            break
    return items


def build_recommendations(
    arguments: Dict[str, Any], *, task_id: str, memory_aliases: Dict[str, MemoryCatalogEntry],
    workflow_aliases: Dict[str, Dict[str, Any]], all_workflows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Map the tool output to wire items {id, kind, action, target_id, title, summary}.

    Memory creates are reconciled against all local memories by the Rust client core;
    workflow creates are matched here against ALL of the user's workflows.
    """
    memory_targets = {alias: (entry.id, entry.title) for alias, entry in memory_aliases.items()}
    workflow_targets = {alias: (item["workflow_id"], clean_text(item.get("title"), MAX_TITLE_CHARS))
                        for alias, item in workflow_aliases.items()}
    workflow_pool = [(item["workflow_id"], clean_text(item.get("title"), MAX_TITLE_CHARS)) for item in all_workflows]
    result: List[Dict[str, Any]] = []
    for kind, field, targets, pool in (
        ("memory", "memory_recommendations", memory_targets, []),
        ("workflow", "workflow_recommendations", workflow_targets, workflow_pool),
    ):
        for index, item in enumerate(_sanitize_kind(arguments.get(field), kind, targets, pool, task_id)):
            result.append({"id": recommendation_id(task_id, kind, index), **item})
    return result
