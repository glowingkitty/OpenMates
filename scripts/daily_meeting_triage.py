#!/usr/bin/env python3
"""NOW / LATER / DROP triage of every item in the daily meeting briefing.

The founder is easily pulled away by small issues, so the briefing pre-sorts each item and
proposes a label with a one-line reason; the founder only confirms or changes it:

- NOW: serves a current priority (read from FOCUS.md "Current priorities") or is evidence that
  real users are affected (production errors, unprocessed production reports, failed requests,
  payment or signup problems) or is due today.
- LATER: still useful, with a proposed date.
- DROP: fits no priority and has no reason to keep; the proposal is to close or archive it.

Clear noise (the `Noise:` line of FOCUS.md: unused providers, dev-only errors, cache warnings,
test timing) is DROP automatically; reported issues that recent commits likely fixed are LATER.
The meeting talks through NOW items only; everything else lands in one "Side notes" section at
the very end of the briefing. Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from datetime import date, timedelta
import re

from daily_meeting_paused import PRIORITY_TOPICS, TASK_PRIORITY

LATER_DAYS = 7
DAILY_NOW_LIMIT = 3  # at most 3 waiting chats and 3 reminders are discussed as NOW per meeting
STALE_DAYS = 60
SIDE_CAP = {"Task": 15, "Reminder": 15, "Issue": 15, "Dev error": 10, "Dev report": 10}  # chats and prod items never capped
DEFAULT_NOISE = ("baseten", "cache warning", "cache miss", "test timing", "flaky", "slow test", "deprecat")
USER_IMPACT = re.compile(r"\b(outage|is down|failed request|request failed|payment|billing|checkout|invoice|"
                         r"sign-?up|signup|login|log in|cannot (log|sign|pay)|user report)\b", re.I)
STOP = {"with", "from", "that", "this", "when", "after", "before", "into", "does", "doesn", "should", "would",
        "error", "issue", "failed", "chat", "task", "page", "user", "fix", "bug"}
FEATURE = re.compile(r"\s*(add|implement|build|support|create)\b", re.I)
SECTION = re.compile(r"^## Current priorities\s*$(.*?)(?=^## |\Z)", re.M | re.S)


def read_priorities(focus_text: str) -> tuple[list[tuple[str, re.Pattern]], tuple[str, ...], str]:
    """(priorities, noise words, data gap) from FOCUS.md `## Current priorities`.

    Lines: `- <name>: word, word, ...` and `Noise: word, ...`. Without the section the built-in
    defaults are used and the gap says so, so a missing section is visible, never silent.
    """
    match = SECTION.search(focus_text or "")
    if not match:
        return list(PRIORITY_TOPICS), DEFAULT_NOISE, "FOCUS.md has no 'Current priorities' section; built-in priorities used"
    topics, noise = [], DEFAULT_NOISE
    for line in match.group(1).splitlines():
        name, _, words = line.lstrip("- ").partition(":")
        parts = [re.escape(w.strip()) for w in words.split(",") if w.strip()]
        if not parts:
            continue
        if name.strip().lower() == "noise":
            noise = tuple(w.strip().lower() for w in words.split(",") if w.strip())
        else:
            topics.append((name.strip(), re.compile(r"\b(" + "|".join(parts) + r")", re.I)))
    return (topics or list(PRIORITY_TOPICS)), noise, ""


def later_date(today: date, days: int = LATER_DAYS) -> date:
    """A proposed date `days` ahead, moved off the weekend."""
    target = today + timedelta(days=days)
    return target + timedelta(days=(7 - target.weekday()) % 7 if target.weekday() >= 5 else 0)


class Triage:
    """Classifies items with the priorities of FOCUS.md; every verdict is {label, reason, date}."""

    def __init__(self, focus_text: str, commits: list[dict], today: date):
        self.topics, self.noise, self.gap = read_priorities(focus_text)
        self.today = today
        self.notes: list[tuple[str, str, dict]] = []
        self.fixes = [c.get("subject", "") for c in commits or [] if re.match(r"\s*(fix|bug)", c.get("subject", ""), re.I)]

    # ── building blocks ──
    def topic(self, text: str) -> str:
        return next((name for name, rx in self.topics if rx.search(text or "")), "")

    def _noise(self, text: str) -> str:
        low = (text or "").lower()
        return next((w for w in self.noise if w in low), "")

    def _v(self, label: str, reason: str, when: date | str = "") -> dict:
        return {"label": label, "reason": reason, "date": str(when) if when else ""}

    def now_or_later(self, text: str, *, urgent: bool = False, due_today: bool = False, days: int = LATER_DAYS,
                     stale: bool = False) -> dict:
        word = self._noise(text)
        if word:
            return self._v("DROP", f"noise ({word})")
        topic = self.topic(text)
        if topic:
            return self._v("NOW", f"serves {topic}")
        if USER_IMPACT.search(text or ""):
            return self._v("NOW", "real users may be affected")
        if urgent:
            return self._v("NOW", "urgent or high priority")
        if due_today:
            return self._v("NOW", "due today")
        if stale:
            return self._v("DROP", f"fits no priority and untouched for {STALE_DAYS}+ days: close it")
        return self._v("LATER", "fits no current priority, still useful", later_date(self.today, days))

    def likely_fixed(self, title: str) -> str:
        words = {w for w in re.findall(r"[a-z]{4,}", (title or "").lower())} - STOP
        return next((s for s in self.fixes if len(words & set(re.findall(r"[a-z]{4,}", s.lower()))) >= 2), "")

    def cap_now(self, entries: list[tuple[str, dict]], noun: str, limit: int = DAILY_NOW_LIMIT) -> None:
        """Daily limit: of `entries` (key, verdict) in importance order only `limit` stay NOW; the rest become LATER."""
        seen = 0
        for _, verdict in entries:
            if verdict["label"] != "NOW":
                continue
            seen += 1
            if seen > limit:
                verdict.update(label="LATER", date=str(later_date(self.today, 1)),
                               reason=f"daily limit of {limit} {noun} as NOW (otherwise NOW: {verdict['reason']})")

    def keep(self, kind: str, title: str, verdict: dict) -> bool:
        """True for NOW (stays in its section); anything else is collected once for the Side notes."""
        if verdict["label"] == "NOW":
            return True
        if not any(k == kind and t == title for k, t, _ in self.notes):
            self.notes.append((kind, title, verdict))
        return False

    @staticmethod
    def tag(verdict: dict) -> str:
        return f" _[NOW: {verdict['reason']}]_"

    # ── items ──
    def chat(self, chat: dict, task: dict | None = None) -> dict:
        text = " ".join(str(chat.get(k, "")) for k in ("title", "needs", "task_title", "last_prompt"))
        verdict = self.now_or_later(text, urgent=(task or {}).get("priority") in ("urgent", "high"))
        if verdict["label"] == "LATER" and chat.get("signal") == "reports it is done":
            return self._v("DROP", "finished work with no open question: archive it")
        return verdict

    def paused(self, row: dict) -> dict:
        if row.get("flag") or row.get("resume_due"):
            return self._v("NOW", "resume date reached or pause note incomplete")
        return self._v("LATER", "paused, state saved", row.get("resume") or later_date(self.today))

    def issue(self, env: str, issue: dict) -> dict:
        title = issue.get("title", "")
        if env == "dev":
            return self.now_or_later(title)
        fix = self.likely_fixed(title)
        if fix:
            return self._v("LATER", f"likely fixed by recent commit \"{fix[:70]}\": confirm, then close",
                           later_date(self.today, 1))
        if not issue.get("processed"):
            return self._v("NOW", "production user report not yet addressed")
        return self._v("LATER", "production report already processed", later_date(self.today, 2))

    def error(self, env: str, err: dict) -> dict:
        text = f"{err.get('service', '')} {err.get('where', '')} {err.get('message', '')}"
        word = self._noise(text)
        if word:
            return self._v("DROP", f"noise ({word})")
        if env == "dev":
            return self._v("DROP", "dev-only error")
        return self._v("NOW", "production error: real users may be affected")

    def task(self, task: dict) -> dict:
        if "idea" in (task.get("labels") or []) and task.get("priority") != "urgent":
            monday = self.today + timedelta(days=7 - self.today.weekday())
            return self._v("LATER", "idea inbox: reviewed in the weekly goals block", monday)
        text = f"{task.get('title', '')} {' '.join(task.get('labels') or [])}"
        stale = task.get("status") == "backlog" and TASK_PRIORITY.get(task.get("priority"), 4) == 4
        verdict = self.now_or_later(text, urgent=task.get("priority") in ("urgent", "high"), stale=stale)
        if verdict["label"] == "LATER" and ("feature" in (task.get("labels") or []) or FEATURE.match(task.get("title", ""))):
            verdict["reason"] = "feature without a user-gain case: idea inbox, ranked by likelihood to gain users"
        return verdict

    def reminder(self, item: dict, due: date | None) -> dict:
        verdict = self.now_or_later(f"{item.get('title', '')} {item.get('list', '')}", due_today=bool(due and due <= self.today))
        if verdict["label"] == "LATER" and due and due > self.today:
            verdict["date"] = str(due)
        return verdict

    def external(self, issue: dict) -> dict:
        updated = str(issue.get("updated", ""))[:10]
        try:
            old = (self.today - date.fromisoformat(updated)).days >= STALE_DAYS
        except ValueError:
            old = False
        return self.now_or_later(issue.get("title", ""), stale=old)


def side_note_lines(notes: list[tuple[str, str, dict]], gap: str = "") -> list[str]:
    """The one short "Side notes" section at the very end: every non-NOW item with its proposal."""
    out = ["", f"## Side notes ({len(notes)}) — not discussed unless the founder asks", "",
           "_LATER and DROP items, each with the proposed label and reason. Confirming this section "
           "executes the proposals: a LATER chat writes its state into its Task with the resume date and is "
           "archived (the briefing brings it back on that date); a DROP is archived or closed, never deleted, "
           "and logged with its reason in the decision log. Say \"change <item> to NOW\" for any you disagree with._", ""]
    if gap:
        out += [f"_Triage gap: {gap}._", ""]
    for kind in ("Chat", "Paused chat", "Production report", "Dev report", "Production error", "Dev error",
                 "Task", "Reminder", "Issue"):
        rows = [(title, v) for k, title, v in notes if k == kind]
        if not rows:
            continue
        out.append(f"**{kind}s ({len(rows)})**")
        for title, v in rows[:SIDE_CAP.get(kind, len(rows))]:
            when = f" {v['date']}" if v.get("date") else ""
            out.append(f"- {title} → **{v['label']}{when}** — {v['reason']}")
        if len(rows) > SIDE_CAP.get(kind, len(rows)):
            out.append(f"- … {len(rows) - SIDE_CAP[kind]} more, same proposals (full lists in the appendices)")
        out.append("")
    if not notes:
        out.append("_Nothing: every item is NOW._")
    return out
