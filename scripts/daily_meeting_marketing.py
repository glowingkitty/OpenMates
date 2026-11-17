#!/usr/bin/env python3
"""Marketing and business development as a fixed part of every daily meeting (Block 2).

Provides the inputs of that block from private state, so the list is never empty:
- the **menu**: 20-minute actions read from the private marketing repository
  (`daily-meeting/marketing-menu.md`: `- <name> | <home|anywhere> | <done line> | after: <name>, <name>`,
  plus a `Marketing finished:` line), built-in neutral defaults with a visible gap otherwise;
- **fresh ideas**: seeds from the marketing repository's `ideas.md`, the ideas already offered in the last
  14 days (`Marketing ideas:` lines of the decisions notes, never repeated) and the style rules
  (`marketing-style.md` feedback section, press words) every idea and text must follow;
- the **win counter**: the `Wins:` line of every decisions note (`Wins: messages 4, replies 1, posts 2,
  applications 3`) summed per week, so progress shows before signups move;
- **three proposals per situation** (at home with camera / on the go): least recently picked first
  (`Marketing pick:` lines), skipping items whose prerequisites are not finished
  (`Marketing finished:` lines), and one honest draft sentence on the growth numbers.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re

WIN_KINDS = ("messages", "replies", "posts", "applications")
STYLE_SECTION = re.compile(r"^## Feedback rules from the daily meeting\s*$(.*?)(?=^## |\Z)", re.M | re.S)
DEFAULT_MENU = (
    ("press release", "anywhere", "one paragraph or one press email drafted or sent; done when it is saved or sent", ()),
    ("landing page", "home", "one landing-page change live (headline, video slot or call to action); done when it is deployed", ()),
    ("videos", "home", "one video take recorded or edited; done when the file is saved in the marketing Project", ()),
    ("community posts", "anywhere", "one post in a community where the target users are; done when it is published", ()),
    ("outreach to past paying users", "anywhere",
     "send 5 short messages to lapsed paying users asking why they stopped ({paying_total} have paid ever, "
     "only {active_7d} users were active this week); done when 5 are sent", ()),
    ("press contacts", "anywhere", "write to 3 press contacts; done when 3 emails are sent", ()),
    ("partnerships", "anywhere", "name 3 possible partners and send 1 short proposal; done when it is sent", ()),
    ("business angels", "anywhere", "shortlist 3 business angels and send 1 intro; done when sent", ("videos", "landing page")),
    ("job applications and job search", "anywhere", "send 1 application or 3 job-search messages; done when sent", ()),
)


def read_menu(menu_text: str) -> tuple[list[tuple], str]:
    """(menu, data gap); the built-in menu is used, with a visible gap, when the marketing repo has none."""
    menu = []
    for line in (menu_text or "").splitlines():
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) >= 3 and parts[0]:
            after = tuple(w.strip().lower() for w in re.sub(r"(?i)^after:", "", parts[3]).split(",") if w.strip()) if len(parts) > 3 else ()
            menu.append((parts[0], "home" if parts[1].lower() == "home" else "anywhere", parts[2], after))
    if menu:
        return menu, ""
    return list(DEFAULT_MENU), "marketing repo has no daily-meeting/marketing-menu.md; built-in menu used"


def finished_in_menu(menu_text: str) -> set[str]:
    found = re.search(r"(?im)^Marketing finished:\s*(.+)$", menu_text or "")
    return {w.strip().lower() for w in found.group(1).split(",")} if found else set()


def parse_wins(note: str) -> dict[str, int]:
    line = re.search(r"(?im)^Wins:\s*(.+)$", note or "")
    pairs = [(kind.lower(), int(n)) for kind, n in re.findall(r"(\w+)\s+(\d+)", line.group(1))] if line else []
    return {kind: n for kind, n in pairs if kind in WIN_KINDS}


def history(out: Path, today: date) -> dict:
    """Wins, picks and finished items from the earlier decisions notes in `out`."""
    wins, picks, finished, ideas = {}, {}, set(), []
    for path in sorted(out.glob("????-??-??-decisions.md")):
        day = path.name[:10]
        if day >= today.isoformat():
            continue
        text = path.read_text(errors="replace")
        wins[day] = parse_wins(text)
        for pick in re.findall(r"(?im)^Marketing pick:\s*(.+)$", text):
            picks[pick.split("(")[0].strip().lower()] = day
        ideas += [(day, i.strip()) for i in re.findall(r"(?im)^Marketing ideas:\s*(.+)$", text)]
        for line in re.findall(r"(?im)^Marketing finished:\s*(.+)$", text):
            finished |= {w.strip().lower() for w in line.split(",") if w.strip()}
    return {"wins": wins, "picks": picks, "finished": finished, "ideas": ideas}


def win_counter(wins: dict[str, dict], today: date) -> dict:
    """Last meeting, this week (since Monday, before today) and the last 14 days, per kind plus day streak."""
    monday, total = (today - timedelta(days=today.weekday())).isoformat(), {k: 0 for k in WIN_KINDS}
    week, recent = dict(total), dict(total)
    since14 = (today - timedelta(days=14)).isoformat()
    for day, row in wins.items():
        for kind in WIN_KINDS:
            week[kind] += row.get(kind, 0) if day >= monday else 0
            recent[kind] += row.get(kind, 0) if day >= since14 else 0
    last_day = max(wins, default="")
    streak = 0
    for day in sorted(wins, reverse=True):
        if sum(wins[day].values()) == 0:
            break
        streak += 1
    return {"last": wins.get(last_day, {}), "last_day": last_day, "week": week, "last_14_days": recent, "streak_days": streak}


def proposals(menu: list[tuple], hist: dict, menu_text: str, growth: dict | None) -> dict:
    """Three menu items for each situation, least recently picked first, prerequisites finished."""
    done = hist["finished"] | finished_in_menu(menu_text)
    m = (growth or {}).get("metrics") or {}
    values = {"paying_total": m.get("paying_users_total", "many"),
              "active_7d": (m.get("active_users") or {}).get("last_7_days", "few")}
    out = {}
    for situation in ("home", "on the go"):
        ok = [(i, e) for i, e in enumerate(menu) if (situation == "home" or e[1] == "anywhere") and set(e[3]) <= done]
        ok.sort(key=lambda p: (hist["picks"].get(p[1][0].lower(), ""), p[0]))
        out[situation] = [{"name": e[0], "done": e[2].format(**values) if "{" in e[2] else e[2]} for _, e in ok[:3]]
    return out


def interpretation(growth: dict | None) -> str:
    """One honest draft sentence on the growth numbers: realistic, critical, on the founder's side."""
    if not growth:
        return "Numbers are unavailable today, so no reading; one outreach action still beats waiting."
    week = ((growth["metrics"].get("periods") or {}).get("last_7_days") or {}).get("signups_completed", 0)
    if week == 0:
        return "0 signups in 7 days: people aren't finding us yet, so outreach beats features right now."
    if week < 5:
        return f"{week} signup{'s' if week != 1 else ''} in 7 days is a start but small, so keep reaching out to people instead of building more."
    return f"{week} signups in 7 days is real movement: find which channel they came from and repeat it today."


def style_rules(style_text: str, press_text: str) -> str:
    """Feedback rules from the meeting plus the press word list: what every idea and text must follow."""
    feedback = STYLE_SECTION.search(style_text or "")
    words = re.search(r"^## Words and tone.*?$(.*?)(?=^## |\Z)", press_text or "", re.M | re.S)
    return "\n".join(part.strip() for part in ((feedback.group(1) if feedback else ""), (words.group(1) if words else "")) if part.strip())[:2500]


def collect(out: Path, sources: dict, growth: dict | None, today: date) -> dict:
    """`sources`: private marketing-repo texts {menu, ideas, style, press}."""
    menu_text = sources.get("menu", "")
    menu, gap = read_menu(menu_text)
    hist = history(out, today)
    since = (today - timedelta(days=14)).isoformat()
    return {"menu_gap": gap, "interpretation": interpretation(growth), "counter": win_counter(hist["wins"], today),
            "proposals": proposals(menu, hist, menu_text, growth), "menu_size": len(menu),
            "offered_ideas": [f"{d}: {i}" for d, i in hist["ideas"] if d >= since],
            "idea_seeds": (sources.get("ideas") or "")[:1500], "style": style_rules(sources.get("style", ""), sources.get("press", ""))}


def render(block: dict | None) -> list[str]:
    out = ["", "## Marketing and business development block (fixed, every meeting)", ""]
    if not block:
        return out + ["_Marketing data unavailable._", ""]
    c = block["counter"]
    fmt = lambda row: ", ".join(f"{kind} {row.get(kind, 0)}" for kind in WIN_KINDS)  # noqa: E731 - tiny local formatter
    out += [f"**Draft reading of the growth numbers (one sentence; adjust if the numbers above say otherwise):** "
            f"{block['interpretation']}", "",
            f"**Win counter** (what you report in the decisions note `Wins:` line): last meeting "
            f"({c['last_day'] or 'none yet'}): {fmt(c['last'])}; this week before today: {fmt(c['week'])}; "
            f"last 14 days: {fmt(c['last_14_days'])}; {c['streak_days']} meeting day(s) in a row with at least one win.", "",
            f"**Proposals from the marketing menu** ({block['menu_size']} items; about 20 minutes each; least recently picked first). "
            "Ask whether the founder is at home with the camera or on the go, then offer exactly these 3:"]
    for situation, rows in block["proposals"].items():
        out.append(f"- *{situation}:*")
        out += [f"  {n}. **{r['name']}** — {r['done']}" for n, r in enumerate(rows, 1)] or ["  (menu empty: add items to FOCUS.md)"]
    out += ["", "**Fresh ideas (1-2 every day, next to the 3 proposals; marketing or business development, "
             "concrete, never one already offered):** generate them yourself from the numbers above, the recent "
             "commits and the seeds below; the founder says take, park or drop, recorded in the `Marketing ideas:` line."]
    out += [f"- already offered (do not repeat): {i}" for i in block["offered_ideas"]] or ["- nothing offered yet in the last 14 days"]
    if block["idea_seeds"]:
        out += ["", "Seeds (marketing repository `ideas.md`):", "", "```", block["idea_seeds"].strip(), "```"]
    if block["style"]:
        out += ["", "**Style rules every idea and text must follow** (marketing style guide, feedback rules and press words):", "",
                "```", block["style"], "```"]
    if block["menu_gap"]:
        out += ["", f"_Menu gap: {block['menu_gap']}._"]
    return out + [""]
