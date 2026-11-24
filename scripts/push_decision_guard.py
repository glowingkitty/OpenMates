"""Validate decision pushes and recognize answers in the same chat lineage."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import owner_message

COMPLETION = re.compile(
    r"(?i)(?:^|[.!;]\s+)\s*(?:done\b|finished\b|completed\b)|"
    r"\b(?:tests?|checks?|proof|verification|(?:the )?build|ci|e2e)"
    r"\s+(?:all\s+)?(?:passed|succeeded|(?:is|are)\s+green)\b|"
    r"\bpassed\s+(?:the\s+)?(?:tests?|checks?|verification)\b|"
    r"\b(?:shipped|deployed|finished|completed)\s+(?:successfully|to dev|to production|and verified)\b|"
    r"\b(?:work|fix|change|feature|recovery)\s+(?:is|are)\s+(?:done|finished|live|complete)\b",
)
INVITATION = re.compile(r"(?i)^(?:any (?:questions|thoughts|feedback)|sound good|is that all|all done|anything else)\s*\?$")
ANSWER = re.compile(
    r"(?i)\b(?:approved|waived|waive|go ahead|you may|no further approval|no separate approval|"
    r"no need to ask|approval is already given|do not (?:deploy|run|ship|merge|continue)|"
    r"skip (?:the )?(?:tests?|proof|verification)|make sure|please (?:run|deploy|ship|retry|requeue))\b"
)
BARE_ANSWER = re.compile(r"(?i)^\s*(?:yes|no|approved|go ahead|do it|waived)[.!\s]*$")
WAIVER = re.compile(r"(?i)\b(?:waiv\w*|skip\w*|without (?:a |the )?(?:test|proof|verification))\b")
APPROVAL = re.compile(r"(?i)\b(?:approve\w*|waiv\w*|permission|may (?:i|we)|go-ahead|sign[- ]off)\b")
HEADER = re.compile(r"receipt ([0-9a-f]{16})\b")
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
STOP = set(("can could you should shall may would please approve approval allow waive waiver permission "
            "the a an for this that about our my we i it to on of and now already with start proceed "
            "investigation failure timed out which when what do does no need any your plan").split())
ALIASES = {"testing": "test", "tests": "test", "scheduled": "queue", "queued": "queue",
           "queueing": "queue", "requeue": "queue", "requeued": "queue", "chats": "chat"}


def shape_error(question: str, recommendation: str, options: list[str]) -> str:
    """Return a precise correction for an invalid question push."""
    if COMPLETION.search(question):
        return "This reports finished work. Use done for the result and ask separately about any open decision."
    if not question.endswith("?") or question.count("?") != 1 or len(re.findall(r"\w+", question)) < 2:
        return "An ask push needs one clear question ending in a question mark."
    if INVITATION.fullmatch(question):
        return "An ask push needs a decision Marco must make."
    generic = {"open the chat and answer", "your choice", "you decide", "none", "n/a"}
    suggestion = recommendation.strip(" .").casefold()
    if (not suggestion or suggestion in generic or "?" in suggestion) and len(set(options)) < 2:
        return "An ask push needs a recommendation or two distinct options."
    if "?" in suggestion or any("?" in option for option in options):
        return "Put the question in the question field and use plain answers as recommendations or options."
    return ""


def words(text: str) -> set[str]:
    return {ALIASES.get(term, term) for term in re.findall(r"[a-z0-9]+(?::[0-9]+)?", text.casefold())
            if term not in STOP and (len(term) >= 2 or term.isdigit())}


def scope_matches(question: str, answer: str) -> bool:
    """Require concrete shared scope and avoid treating unrelated approvals as answers."""
    expected = words(question)
    if len(expected) < 2:
        return False
    actual = words(answer)
    # Never carry a dev authorization into a production decision.
    scope = expected & {"production", "prod", "dev", "staging", "preview"}
    scope = {"production" if term == "prod" else term for term in scope}
    environments = {"production" if term == "prod" else term for term in actual}
    if scope and not scope <= environments:
        return False
    if WAIVER.search(question) and not WAIVER.search(answer):
        return False
    shared = expected & actual
    times = {term for term in expected if ":" in term}
    if times and not times <= actual:
        return False
    if "prod" in expected and "production" in actual or "production" in expected and "prod" in actual:
        shared |= expected & {"production", "prod"}
    return expected <= actual or (len(shared) >= 2 and len(shared) * 3 >= len(expected) * 2)


def lineage(root: Path, chat_id: str) -> set[str]:
    try:
        handoffs = json.loads((root / "logs/claude-chat-lifecycle/handed_off.json").read_text())
    except (OSError, ValueError):
        return {chat_id}
    found = {chat_id}
    if not isinstance(handoffs, dict):
        return found
    while True:
        sources = {source for source, row in handoffs.items() if isinstance(row, dict)
                   and found.intersection(re.findall(UUID, str(row.get("successor", ""))))}
        if sources <= found:
            return found
        found.update(sources)


def receipts(root: Path, chats: set[str]) -> list[tuple[str, str, str, float]]:
    """Find candidate receipts in the host delivery log. The broker verifies each match."""
    path = root / "logs/claude-chat-lifecycle/connector-deliveries.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    results = []
    if not isinstance(entries, dict):
        return results
    for key, row in entries.items():
        if not isinstance(row, dict):
            continue
        chat = row.get("chat") or key.partition(":")[0]
        if chat not in chats:
            continue
        body = row.get("body") or ""
        if match := HEADER.search(body.partition("]")[0]):
            results.append((match[1], chat, body.partition("]")[2].strip(), float(row.get("sent_at") or 0)))
    return results


def already_answered(root: Path, chat_id: str, question: str, task: str, now: float, push_log: Path) -> bool:
    """Use only context matched to the same work and confirmed by the owner connector."""
    chats = lineage(root, chat_id)
    try:
        previous = [json.loads(line) for line in (root / push_log).read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        previous = []
    previous = [row for row in previous if row.get("kind") == "ask" and row.get("chat_id") in chats
                and (not task or not row.get("task") or task == row["task"])]
    for receipt, sender, candidate, sent in receipts(root, chats):
        if sent > now:
            continue
        scoped = (APPROVAL.search(question) or WAIVER.search(question)
                  or bool(words(question) & {"queue", "deploy", "ship", "merge"}))
        specific = scoped and ANSWER.search(candidate) and scope_matches(question, candidate)
        older = [row for row in previous if row.get("chat_id") == sender and float(row.get("ts") or 0) < sent]
        last = max(older, key=lambda row: row["ts"], default={})
        exact_prior = bool(last) and words(last.get("asks", "")) == words(question)
        bare = exact_prior and (BARE_ANSWER.fullmatch(candidate) or
                               candidate.strip(" .").casefold() in
                               {option.casefold() for option in last.get("options") or []})
        if not (specific or bare):
            continue
        try:
            answer = owner_message.ask_broker(receipt)
            valid, _ = owner_message.check(answer, sender)
            raw = answer.partition("\ntext: ")[2].strip()
            verified_at = datetime.fromisoformat(answer.split("\nsent: ", 1)[1].split("\n", 1)[0]).timestamp()
        except (OSError, ValueError, IndexError):
            continue
        if not valid or verified_at > now:
            continue
        if ((specific and ANSWER.search(raw) and scope_matches(question, raw))
                or (bare and verified_at > last["ts"] and raw == candidate)):
            return True
    return False
