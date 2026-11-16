#!/usr/bin/env python3
"""Opportunities (events, jobs): private profiles, daily searches, tracking lists.

Personal data, never in the repository. Everything lives in one private folder on the
dev host (`~/.local/state/openmates/opportunities/`, mode 0700; override with
OPENMATES_OPPORTUNITIES_DIR). It is the shared memory of the dedicated Events and Jobs
chats, so their context survives across sessions:
  jobs-profile.md    living memory: experience/CV, jobs wanted, criteria, writing style.
                     Starts empty; the Jobs chat fills it in (first-time setup conversation).
  events-profile.md  interests, cities with dates (asked, never assumed), time window.
  tracking.json      every event and job ever found: status new / interested /
                     signed_up / applied / skipped, dates, deadline, links, notes, history.
  last-search.json   counts and quality warnings of the last daily search.
  history/           a dated copy of a file before each change (local undo).

The briefing build (scripts/daily_meeting_briefing.py) calls `collect()`: it searches with
the dev server's own skills through the installed CLI (`openmates apps events search` /
`openmates apps jobs search`, logged-in personal dev account, dev API) and appends only NEW
items to the tracking lists. The daily meeting shows one line per area plus deadlines of the
next 3 days; the items themselves are handled in the Events and Jobs chats, which use the
commands below through the private dev connector.

  collect | summary
  read --area events|jobs [--status S] [--include-skipped]
  set-status --area A --item "<title or [id]>" --status interested|skip|sign up|apply [--notes] [--deadline YYYY-MM-DD]
  add-item --area A --title T --url U [--when YYYY-MM-DD[THH:MM]] [--notes]
  profile --area A --section "<heading>" --action set|add --text "<text>"
Docs: docs/contributing/guides/daily-meeting.md (section "Opportunities")
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
SHOW = 5
SEARCH_TIMEOUT = 240
EVENT_PROVIDERS = ["meetup", "luma", "eventbrite"]
STATUSES = {"new": "new", "interested": "interested", "interest": "interested", "skip": "skipped",
            "skipped": "skipped", "sign up": "signed_up", "signed up": "signed_up", "signup": "signed_up",
            "signed_up": "signed_up", "apply": "applied", "applied": "applied"}

JOBS_TEMPLATE = """\
# Jobs profile (private, living memory)
_Status: empty. The Jobs chat fills this in through conversation (first-time setup)._

## Search
<!-- The daily briefing searches with these `key: value` lines; values split at ";". -->
queries:
countries:
locations:
remote:
employment_type:
relevance:

## Experience and CV

## Jobs wanted

## Criteria (role, location or remote, type)

## Writing style for applications

## Notes
"""

EVENTS_TEMPLATE = """\
# Events profile (private, living memory)

## Search
<!-- cities: "City from YYYY-MM-DD until YYYY-MM-DD"; separate cities with ";". Ask, never assume. -->
queries: AI; tech meetup; startup founders; social
cities:
window_days: 14
relevance: AI and tech events and social events where a solo founder meets builders and potential users

## Interests
- AI and tech events
- Social events

## Travel and cities

## Notes
"""


# ── Private store ─────────────────────────────────────────────────────────────

def home() -> Path:
    path = Path(os.environ.get("OPENMATES_OPPORTUNITIES_DIR")
                or Path.home() / ".local" / "state" / "openmates" / "opportunities")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    for name, text in (("jobs-profile.md", JOBS_TEMPLATE), ("events-profile.md", EVENTS_TEMPLATE)):
        if not (path / name).exists():
            _write(path / name, text)
    return path


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def _snapshot(path: Path) -> None:
    """Keep the previous version before a change (history/<name>.<timestamp>)."""
    if path.exists():
        folder = path.parent / "history"
        folder.mkdir(mode=0o700, exist_ok=True)
        shutil.copy2(path, folder / f"{path.name}.{datetime.now(TZ):%Y%m%d-%H%M%S}")


def load_tracking(folder: Path) -> dict:
    path = folder / "tracking.json"
    if not path.exists():
        return {"events": {}, "jobs": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("events", {})
    data.setdefault("jobs", {})
    return data


def save_tracking(folder: Path, data: dict) -> None:
    _snapshot(folder / "tracking.json")
    _write(folder / "tracking.json", json.dumps(data, indent=1, ensure_ascii=False))


# ── Profiles ──────────────────────────────────────────────────────────────────

def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) per `## ` heading; index 0 is the preamble with heading ''."""
    parts = re.split(r"(?m)^## ", text)
    out = [("", parts[0])]
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        out.append((heading.strip(), body))
    return out


def _join(sections: list[tuple[str, str]]) -> str:
    text = sections[0][1]
    for heading, body in sections[1:]:
        text += f"## {heading}\n{body}"
    return text


def search_settings(text: str) -> dict[str, str]:
    body = next((b for h, b in _sections(text) if h.lower() == "search"), "")
    settings = {}
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[a-z_]+", key.strip()):
            settings[key.strip()] = value.strip()
    return settings


def values(setting: str) -> list[str]:
    return [v.strip() for v in re.split(r"[;\n]", setting or "") if v.strip()]


def jobs_profile_empty(text: str) -> bool:
    return not values(search_settings(text).get("queries", ""))


def parse_cities(setting: str, today: date, window: int) -> list[tuple[str, date, date]]:
    """'Munich until 2026-11-17; Berlin from 2026-11-18' -> (city, start, end) inside the window."""
    last = today + timedelta(days=window)
    out = []
    for entry in values(setting):
        start = re.search(r"\bfrom\s+(\d{4}-\d{2}-\d{2})", entry)
        until = re.search(r"\b(?:until|to)\s+(\d{4}-\d{2}-\d{2})", entry)
        city = re.split(r"\s+\b(?:from|until|to)\b", entry)[0].strip(" ,()")
        begin = max(today, date.fromisoformat(start.group(1))) if start else today
        end = min(last, date.fromisoformat(until.group(1))) if until else last
        if city and begin <= end:
            out.append((city, begin, end))
    return out


def update_profile(text: str, section: str, action: str, value: str, today: date) -> str:
    """Apply one Profile updates row. Search section: `set key: value`; others: set or add a bullet."""
    sections = _sections(text)
    wanted = section.strip().lower()
    index = next((i for i, (h, _) in enumerate(sections) if i and h.lower().startswith(wanted)), None)
    if index is None:
        sections.append((section.strip(), "\n"))
        index = len(sections) - 1
    heading, body = sections[index]
    if heading.lower() == "search":
        key, sep, val = value.partition(":")
        if not sep:
            raise ValueError("Search rows need `key: value` (e.g. `queries: AI engineer; founding engineer`)")
        key = key.strip().lower()
        line = f"{key}: {val.strip()}" if action == "set" else None
        lines = body.splitlines()
        hit = next((i for i, row in enumerate(lines) if row.split(":")[0].strip().lower() == key), None)
        if action == "add" and hit is not None:
            old = lines[hit].partition(":")[2].strip()
            line = f"{key}: {old + '; ' if old else ''}{val.strip()}"
        elif action == "add":
            line = f"{key}: {val.strip()}"
        if hit is None:
            insert = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), len(lines) - 1) + 1
            lines.insert(insert, line)
        else:
            lines[hit] = line
        body = "\n".join(lines) + "\n"
    elif action == "set":
        body = f"\n{value.strip()}\n\n"
    else:
        kept = body.rstrip("\n")
        body = f"{kept}\n- {value.strip()} ({today.isoformat()})\n\n"
    sections[index] = (heading, body)
    preamble = re.sub(r"(?m)^_Status: empty\..*\n", "", sections[0][1])
    sections[0] = ("", preamble)
    return _join(sections)


# ── Searches through the dev server's own skills ─────────────────────────────

def _cli(app: str, requests: list[dict]) -> dict:
    run = subprocess.run(["openmates", "apps", app, "search", "--input", json.dumps({"requests": requests}),
                          "--json"], capture_output=True, text=True, timeout=SEARCH_TIMEOUT)
    if run.returncode:
        raise RuntimeError((run.stderr or run.stdout).strip()[-300:])
    reply = json.loads(run.stdout)
    return reply.get("data", reply) if isinstance(reply, dict) else {}


def _key(prefix: str, *parts: str) -> str:
    text = "|".join(re.sub(r"\W+", " ", p or "").strip().casefold() for p in parts)
    return f"{prefix}-{hashlib.sha1(text.encode()).hexdigest()[:5]}"


def _venue(event: dict) -> str:
    venue = event.get("venue") or {}
    if isinstance(venue, dict):
        return ", ".join(filter(None, [venue.get("name"), venue.get("city")]))
    return str(venue)


def search_events(profile: str, today: date, quality: list[str]) -> list[dict]:
    settings = search_settings(profile)
    window = int(settings.get("window_days") or 14)
    cities = parse_cities(settings.get("cities", ""), today, window)
    queries = values(settings.get("queries", ""))
    if not cities or not queries:
        return []
    requests = []
    for city, begin, end in cities:
        for query in queries:
            requests.append({"id": f"{len(requests) + 1}", "query": query, "location": city,
                             "start_date": f"{begin.isoformat()}T00:00:00+01:00",
                             "end_date": f"{end.isoformat()}T23:59:00+01:00", "event_type": "PHYSICAL",
                             "count": 25, "providers": EVENT_PROVIDERS,
                             **({"relevance_criteria": settings["relevance"]} if settings.get("relevance") else {})})
    data = _cli("events", requests)
    quality += [f"events: {w}" for w in data.get("warnings") or []]
    found: dict[str, dict] = {}
    groups = data.get("results") or []
    for index, group in enumerate(groups):
        rows = group.get("results") or []
        request = requests[index] if index < len(requests) else {}
        if not rows:
            quality.append(f"events: no results for {request.get('query')!r} in {request.get('location')}")
        for rank, event in enumerate(rows):
            day = str(event.get("date_start") or "")[:10]
            key = _key("E", event.get("title", ""), day)
            if key not in found:
                found[key] = {"id": key, "title": event.get("title", ""), "url": event.get("url", ""),
                              "date": event.get("date_start", ""), "where": _venue(event),
                              "city": request.get("location", ""), "source": event.get("provider", ""),
                              "query": request.get("query", ""), "rank": rank}
    return sorted(found.values(), key=lambda e: (e["rank"], e["date"]))


def search_jobs(profile: str, quality: list[str]) -> list[dict]:
    settings = search_settings(profile)
    queries = values(settings.get("queries", ""))
    countries = [c.upper() for c in values(settings.get("countries", ""))] or [""]
    locations = values(settings.get("locations", "")) or [""]
    remote = settings.get("remote", "").lower()
    requests = []
    for query in queries:
        for country in countries:
            for location in locations:
                item = {"id": f"{len(requests) + 1}", "query": query, "limit": 15, "max_days_old": 30}
                if country:
                    item["country"] = country
                if location:
                    item["location"] = location
                if remote in ("yes", "true", "only"):
                    item["remote"] = True
                if settings.get("employment_type"):
                    item["employment_type"] = settings["employment_type"]
                if settings.get("relevance"):
                    item["relevance_criteria"] = settings["relevance"][:1000]
                requests.append(item)
    data = _cli("jobs", requests)
    for warning in data.get("warnings") or []:
        quality.append(f"jobs: {warning.get('message') if isinstance(warning, dict) else warning}")
    found: dict[str, dict] = {}
    for index, group in enumerate(data.get("results") or []):
        rows = group.get("results") or []
        request = requests[index] if index < len(requests) else {}
        if not rows:
            quality.append(f"jobs: no results for {request.get('query')!r}"
                           + (f" in {request.get('country')}" if request.get("country") else ""))
        for rank, job in enumerate(rows):
            key = _key("J", job.get("title", ""), job.get("company", ""))
            if key not in found:
                found[key] = {"id": key, "title": job.get("title", ""), "company": job.get("company") or "",
                              "url": job.get("apply_url") or job.get("url", ""),
                              "where": job.get("location") or job.get("country") or "",
                              "remote": bool(job.get("remote")), "type": job.get("employment_type") or "",
                              "source": str(job.get("id", "")).split(":")[0], "query": request.get("query", ""),
                              "summary": _plain(job.get("description") or "")[:400], "rank": rank}
    return sorted(found.values(), key=lambda j: j["rank"])


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _pick_new(kind: str, found: list[dict], tracking: dict, today: date) -> list[dict]:
    """Items already shown today stay (rebuilds), then unseen ones; never an item from an earlier day."""
    store = tracking[kind]
    shown_today = [dict(store[i["id"]], id=i["id"]) for i in found
                   if i["id"] in store and store[i["id"]].get("first_shown") == today.isoformat()
                   and store[i["id"]].get("status") == "new"]
    fresh = [i for i in found if i["id"] not in store]
    chosen = (shown_today + fresh)[:SHOW]
    for item in chosen:
        if item["id"] not in store:
            store[item["id"]] = {k: v for k, v in item.items() if k not in ("id", "rank")} | {
                "status": "new", "first_shown": today.isoformat(), "updated": today.isoformat(), "history": []}
    return chosen


def collect(today: date, gaps: list[str]) -> dict:
    """Run today's searches, append the new items to the tracking lists, return the briefing data."""
    folder = home()
    jobs_text = (folder / "jobs-profile.md").read_text(encoding="utf-8")
    events_text = (folder / "events-profile.md").read_text(encoding="utf-8")
    tracking = load_tracking(folder)
    quality: list[str] = []
    settings = search_settings(events_text)
    no_city = not parse_cities(settings.get("cities", ""), today, int(settings.get("window_days") or 14))
    found = {"events": [], "jobs": []}
    if not no_city:
        try:
            found["events"] = _pick_new("events", search_events(events_text, today, quality), tracking, today)
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            gaps.append(f"event search failed ({str(error)[:200]})")
    if not jobs_profile_empty(jobs_text):
        try:
            found["jobs"] = _pick_new("jobs", search_jobs(jobs_text, quality), tracking, today)
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            gaps.append(f"job search failed ({str(error)[:200]})")
    save_tracking(folder, tracking)
    last = {"date": today.isoformat(), "events_found": len(found["events"]), "jobs_found": len(found["jobs"]),
            "quality": list(dict.fromkeys(quality))}
    _write(folder / "last-search.json", json.dumps(last, indent=1, ensure_ascii=False))
    return summary(today, folder) | {"quality": last["quality"]}


def _counts(store: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in store.values():
        counts[row.get("status", "new")] = counts.get(row.get("status", "new"), 0) + 1
    return counts


def _upcoming(kind: str, row: dict, today: date) -> bool:
    """Events count while they lie ahead; jobs while first seen within the last 30 days."""
    if kind == "events":
        return str(row.get("date", ""))[:10] >= today.isoformat()
    return str(row.get("first_shown", "")) >= (today - timedelta(days=30)).isoformat()


def summary(today: date, folder: Path | None = None) -> dict:
    """Counts per area and the deadlines of the next 3 days (event dates, job deadlines)."""
    folder = folder or home()
    tracking = load_tracking(folder)
    jobs_text = (folder / "jobs-profile.md").read_text(encoding="utf-8")
    events_text = (folder / "events-profile.md").read_text(encoding="utf-8")
    settings = search_settings(events_text)
    out: dict = {"folder": str(folder), "jobs_empty": jobs_profile_empty(jobs_text),
                 "events_no_city": not parse_cities(settings.get("cities", ""), today,
                                                    int(settings.get("window_days") or 14))}
    for kind in ("events", "jobs"):
        rows = [r for r in tracking[kind].values() if _upcoming(kind, r, today)]
        out[kind] = {"new": sum(r.get("status") == "new" for r in rows),
                     "new_today": sum(r.get("status") == "new" and r.get("first_shown") == today.isoformat()
                                      for r in rows),
                     "interested": sum(r.get("status") == "interested" for r in rows)}
    horizon = (today + timedelta(days=3)).isoformat()
    deadlines = []
    for kind, statuses in (("events", ("interested", "signed_up")), ("jobs", ("new", "interested"))):
        for key, row in tracking[kind].items():
            when = str(row.get("deadline") or (row.get("date") if kind == "events" else "") or "")[:10]
            if row.get("status") in statuses and today.isoformat() <= when <= horizon:
                deadlines.append({"kind": kind[:-1], "id": key, "title": row.get("title", ""), "when": when,
                                  "status": row.get("status")})
    out["deadlines"] = sorted(deadlines, key=lambda d: d["when"])
    return out


# ── Briefing section: one line per area ───────────────────────────────────────

def summary_lines(data: dict) -> list[str]:
    events, jobs = data["events"], data["jobs"]
    if data["events_no_city"]:
        event_line = "Events: no city with dates in the events profile yet; set it in the Events chat."
    else:
        event_line = (f"Events: {events['new']} new events waiting ({events['new_today']} found today)"
                      + (f", {events['interested']} marked interested" if events["interested"] else "")
                      + "; continue in the Events chat.")
    if data["jobs_empty"]:
        job_line = "Jobs: the jobs profile is not set up yet, so no job search ran; the Jobs chat runs the setup."
    else:
        job_line = (f"Jobs: {jobs['new']} new jobs waiting ({jobs['new_today']} found today)"
                    + (f", {jobs['interested']} marked interested" if jobs["interested"] else "")
                    + "; continue in the Jobs chat.")
    lines = [f"- {event_line}", f"- {job_line}"]
    for item in data.get("deadlines") or []:
        lines.append(f"- Deadline {item['when']}: {item['title']} ({item['kind']}, {item['status'].replace('_', ' ')})")
    return lines


def render(data: dict | None) -> list[str]:
    out = ["", "## Opportunities (events and jobs; handled in their own chats)", ""]
    if not data:
        return out + ["_Opportunities unavailable — see data gaps._", ""]
    return out + summary_lines(data) + [""]


# ── Shared memory for the dedicated Events / Jobs chats ───────────────────────

def _area(area: str) -> str:
    area = area.strip().lower()
    if area in ("event", "events"):
        return "events"
    if area in ("job", "jobs"):
        return "jobs"
    raise ValueError("area must be events or jobs (email is not set up yet)")


def read_area(area: str, status: str = "", include_skipped: bool = False, today: date | None = None) -> str:
    """Profile, open items (newest first) and the last search's quality notes, as plain text."""
    kind = _area(area)
    today = today or datetime.now(TZ).date()
    folder = home()
    profile = (folder / f"{kind}-profile.md").read_text(encoding="utf-8")
    store = load_tracking(folder)[kind]
    wanted = STATUSES.get(status.strip().lower()) if status else None
    if status and not wanted:
        raise ValueError("status must be new, interested, signed_up, applied or skipped")
    rows = [(k, v) for k, v in store.items()
            if (v.get("status") == wanted if wanted else (include_skipped or v.get("status") != "skipped"))
            and (wanted or include_skipped or _upcoming(kind, v, today) or v.get("status") in ("signed_up", "applied"))]
    rows.sort(key=lambda kv: (kv[1].get("date") or kv[1].get("first_shown") or ""), reverse=kind == "jobs")
    out = [f"# {kind.title()}: shared memory ({folder})", "", "## Profile", profile.strip(), "",
           f"## Items ({len(rows)} shown; statuses: {_counts(store)})"]
    for key, row in rows:
        bits = [row.get("status", "new")]
        if kind == "events":
            bits.append(f"{row.get('date', '')[:16]} {row.get('where') or row.get('city', '')}")
        else:
            bits.append(", ".join(filter(None, [row.get("company"), row.get("where"),
                                                "remote" if row.get("remote") else "", row.get("type")])))
        if row.get("deadline"):
            bits.append(f"deadline {row['deadline']}")
        out.append(f"- [{key}] {row.get('title')} — {'; '.join(bits)} — first shown {row.get('first_shown')}"
                   f" — {row.get('url')}")
        if row.get("summary"):
            out.append(f"  {row['summary']}")
        if row.get("notes"):
            out.append(f"  notes: {row['notes']}")
    last_path = folder / "last-search.json"
    if last_path.exists():
        last = json.loads(last_path.read_text(encoding="utf-8"))
        notes = [q for q in last.get("quality", []) if q.startswith(kind)]
        out += ["", f"## Last daily search ({last.get('date')})"] + ([f"- {q}" for q in notes] or ["- no warnings"])
    return "\n".join(out) + "\n"


def set_status(area: str, item: str, status: str, notes: str = "", deadline: str = "",
               today: date | None = None) -> str:
    kind = _area(area)
    today = today or datetime.now(TZ).date()
    wanted = STATUSES.get(status.strip().lower())
    if not wanted:
        raise ValueError("status must be new, interested, signed_up (sign up), applied (apply) or skipped (skip)")
    if deadline and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline):
        raise ValueError("deadline must be YYYY-MM-DD")
    folder = home()
    tracking = load_tracking(folder)
    key, reason = _resolve(item, tracking[kind])
    if not key:
        raise ValueError(reason)
    row = tracking[kind][key]
    row["history"] = row.get("history", []) + [{"from": row.get("status"), "to": wanted, "on": today.isoformat(),
                                                 "notes": notes}]
    row.update(status=wanted, updated=today.isoformat())
    if notes:
        row["notes"] = (row.get("notes", "") + f" | {today}: {notes}").strip(" |")
    if deadline:
        row["deadline"] = deadline
    save_tracking(folder, tracking)
    check = load_tracking(folder)[kind][key]
    if check.get("status") != wanted:
        raise RuntimeError(f"status not saved (still {check.get('status')})")
    return f"OK: {row.get('title')} [{key}] is now {wanted}" + (f", deadline {deadline}" if deadline else "")


def add_item(area: str, title: str, url: str, when: str = "", notes: str = "",
             today: date | None = None) -> str:
    """An item the founder found elsewhere, so it is tracked like a search result."""
    kind = _area(area)
    today = today or datetime.now(TZ).date()
    folder = home()
    tracking = load_tracking(folder)
    key = _key(kind[0].upper(), title, when[:10] if kind == "events" else url)
    if key in tracking[kind]:
        return f"Already tracked: {title} [{key}] ({tracking[kind][key].get('status')})"
    tracking[kind][key] = {"title": title, "url": url, "date": when if kind == "events" else "",
                           "deadline": when if kind == "jobs" else "", "source": "added in chat",
                           "notes": notes, "status": "interested", "first_shown": today.isoformat(),
                           "updated": today.isoformat(), "history": []}
    save_tracking(folder, tracking)
    return f"OK: added {title} [{key}] as interested"


def edit_profile(area: str, section: str, action: str, text: str, today: date | None = None) -> str:
    kind = _area(area)
    if action not in ("set", "add") or not section.strip() or not text.strip():
        raise ValueError("needs a section, action set or add, and text")
    today = today or datetime.now(TZ).date()
    path = home() / f"{kind}-profile.md"
    updated = update_profile(path.read_text(encoding="utf-8"), section, action, text, today)
    _snapshot(path)
    _write(path, updated)
    check = text.partition(":")[2].strip() if section.strip().lower() == "search" else text.strip()
    if check not in path.read_text(encoding="utf-8"):
        raise RuntimeError("the text is not in the profile after writing")
    return f"OK: {kind} profile, section {section!r}: {action} done"


def _resolve(text: str, store: dict) -> tuple[str | None, str]:
    found = re.search(r"\b([EJ]-[0-9a-f]{5})\b", text)
    if found and found.group(1) in store:
        return found.group(1), ""
    wanted = re.sub(r"\s*\[[^\]]*\]\s*$", "", text).strip().casefold()
    hits = [k for k, v in store.items() if v.get("title", "").strip().casefold() == wanted]
    if len(hits) == 1:
        return hits[0], ""
    return None, ("several tracked items have this title; use the [E-…]/[J-…] id" if hits
                  else "not found among the tracked items; use the id in brackets from the read output")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect")
    sub.add_parser("summary")
    read = sub.add_parser("read")
    read.add_argument("--area", required=True)
    read.add_argument("--status", default="")
    read.add_argument("--include-skipped", action="store_true")
    status = sub.add_parser("set-status")
    status.add_argument("--area", required=True)
    status.add_argument("--item", required=True)
    status.add_argument("--status", required=True)
    status.add_argument("--notes", default="")
    status.add_argument("--deadline", default="")
    add = sub.add_parser("add-item")
    add.add_argument("--area", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--url", required=True)
    add.add_argument("--when", default="")
    add.add_argument("--notes", default="")
    profile = sub.add_parser("profile")
    profile.add_argument("--area", required=True)
    profile.add_argument("--section", required=True)
    profile.add_argument("--action", choices=("set", "add"), required=True)
    profile.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    today = datetime.now(TZ).date()
    try:
        if args.command == "collect":
            gaps: list[str] = []
            data = collect(today, gaps)
            print("\n".join(render(data)))
            for line in data["quality"] + gaps:
                print(f"note: {line}", file=sys.stderr)
        elif args.command == "summary":
            print("\n".join(summary_lines(summary(today))))
        elif args.command == "read":
            print(read_area(args.area, args.status, args.include_skipped, today))
        elif args.command == "set-status":
            print(set_status(args.area, args.item, args.status, args.notes, args.deadline, today))
        elif args.command == "add-item":
            print(add_item(args.area, args.title, args.url, args.when, args.notes, today))
        else:
            print(edit_profile(args.area, args.section, args.action, args.text, today))
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
