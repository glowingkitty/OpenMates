"""Readable `transcript.md` for one AI test user session (the JSON transcript stays next to it)."""

from __future__ import annotations

from typing import Any

from reports import video_moment

EXCERPT_CHARS = 600


def plain_action(action: dict[str, Any], controls: dict[str, str]) -> str:
    kind = action.get("kind")
    target = controls.get(str(action.get("target")), action.get("target"))
    if kind == "type":
        suffix = " and sent it" if action.get("submit") else ""
        return f'typed "{action.get("text", "")}" into {target}{suffix}'
    if kind == "click":
        return f"clicked {target}"
    if kind == "select":
        return f'chose "{action.get("value")}" in {target}'
    if kind == "scroll":
        return f"scrolled by {action.get('delta')} px"
    if kind == "goto":
        return f"opened {action.get('url')}"
    if kind == "wait_for_reply":
        return "waited for the answer"
    return str(kind)


def user_messages(entry: dict[str, Any]) -> list[str]:
    return [str(a.get("text", "")) for a in entry.get("actions", []) if a.get("kind") == "type" and a.get("submit")]


def render(result: dict[str, Any], persona: dict[str, Any], transcript: list[dict[str, Any]], target: str) -> str:
    out = [f"# {persona.get('name', persona.get('id'))} ({persona.get('id')})", ""]
    out += [
        f"- Persona: {persona.get('description', '')}",
        f"- Device: {persona.get('device_label')}, language {persona.get('language')}",
        f"- Target: {target}",
        f"- Status: {result.get('status')} after {result.get('steps', len(transcript))} steps",
        f"- Credits: {result.get('credits_start')} at start, {result.get('credits_end')} at end",
        f"- Costs: harness {result.get('harness_usd')} USD, sandbox {(result.get('e2b') or {}).get('usd')} USD",
        f"- Signup: {_stage(result.get('signup'))}; gift card: {_stage(result.get('gift_card'))}; "
        f"account deletion: {_stage(result.get('deletion'))}",
        f"- Video: {result.get('video_url') or 'not recorded'}"
        + (" (deleted after 7 days)" if result.get("video_url") else ""),
        "",
    ]
    if result.get("summary"):
        out += [f"Summary: {result['summary']}", ""]
    out.append("## Steps")
    for entry in transcript:
        out += ["", f"### Step {entry['step']} ({entry.get('at_seconds')} s) {entry.get('title') or ''}".rstrip()]
        out.append(f"Thought: {entry.get('thought', '')}")
        controls = {}
        actions = [plain_action(a, controls) for a in entry.get("actions", [])]
        out.append("Did: " + ("; ".join(actions) if actions else "nothing"))
        if entry.get("refused"):
            out.append("Refused by test policy: " + "; ".join(entry["refused"]))
        out.append(f"Outcome: {entry.get('outcome', '')}")
        timing = entry.get("reply_timing")
        if timing:
            out.append(
                f"Reply timing: first change after {timing.get('first_change_seconds')} s, "
                f"finished after {timing.get('seconds')} s (settled: {timing.get('settled')})"
            )
        for message in user_messages(entry):
            out.append(f"User message: {message}")
        if timing:
            out.append("Assistant answer (page excerpt): " + _excerpt(entry.get("page_text", "")))
        for note in entry.get("notes", []):
            out.append(f"Persona note [{note.get('category')}]: {note.get('what')}")
    out += ["", "## Findings"]
    findings = result.get("findings") or []
    ids = {tuple(r.get("finding_ids") or []): r for r in result.get("reports", [])}
    for index, finding in enumerate(findings):
        report = next((r for key, r in ids.items() if index in key), None)
        out.append(
            f"- [{finding.get('severity')}] {finding.get('title')} (step {finding.get('step')}, "
            f"Jev {finding.get('jev_score')}, {'kept' if finding.get('kept') else 'dropped'}"
            + (f", report {report.get('short_issue_id')}" if report and report.get("short_issue_id") else "")
            + f"): {finding.get('evidence', '')}"
            + (f" Video: {video_moment(result['video_url'], finding.get('video_seconds'))}"
               if result.get("video_url") else "")
        )
    if not findings:
        out.append("None.")
    out += ["", "## Answer quality", "", "| Step | Question | Score | Why |", "| --- | --- | --- | --- |"]
    for row in result.get("answer_quality") or []:
        cells = [row.get("step"), row.get("question"), row.get("score"), row.get("why")]
        out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    demo = result.get("demo_candidate") or {}
    out += ["", "## Demo candidate", f"{'Yes' if demo.get('is_candidate') else 'No'}: {demo.get('why', '')}"]
    if demo.get("steps"):
        out.append("Steps: " + ", ".join(str(s) for s in demo["steps"]))
    return "\n".join(out) + "\n"


def _stage(stage: Any) -> str:
    if isinstance(stage, dict):
        return f"{stage.get('status')} ({stage.get('seconds', '-')} s)" + (f", {stage['error']}" if stage.get("error") else "")
    return "not run"


def _excerpt(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat[-EXCERPT_CHARS:] if len(flat) > EXCERPT_CHARS else flat
