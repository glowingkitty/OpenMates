"""Synthetic probes: real chats and a real app skill against production.

Each probe sends one tiny request through the public API and reports pass/fail
to a Gatus external endpoint. Probes force the cheapest model (Gemini Flash
Lite) and identify themselves as monitor traffic so production keeps them out
of usage statistics, billing and the anonymous free allowance:
- without an account: the ``X-OpenMates-Monitor-Token`` header;
- with an account: the dedicated monitoring account's API key.
Errors are reduced to short public classes (``timeout``, ``http_503``,
``empty_answer``); response bodies are never stored or forwarded.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable

MODEL_MENTION = "@ai-model:gemini-3.5-flash-lite"
CHAT_PROMPT = f"{MODEL_MENTION} Reply with exactly one word: pong"
SEARCH_PROMPT = (f"{MODEL_MENTION} @skill:web:search Search the web for today's top technology news "
                 "headline and answer with one short sentence.")
CHAT_TIMEOUT_S = 90
SKILL_TIMEOUT_S = 180
MONITOR_HEADER = "X-OpenMates-Monitor-Token"
MONITOR_ANONYMOUS_ID = "status-monitor"
# The ask API substitutes this text when the model produced nothing
# (backend/apps/ai/skills/ask_skill.py); it is a failed chat, not an answer.
EMPTY_REPLY_PLACEHOLDER = "I'm processing your request. Please try again"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one probe run."""

    success: bool
    error: str
    duration_s: float


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


HttpPost = Callable[[str, dict, dict[str, str], float], HttpResponse]


def http_post(url: str, payload: dict, headers: dict[str, str], timeout_s: float) -> HttpResponse:
    """POST JSON and return status and body; HTTP errors are returned, not raised."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "User-Agent": "openmates-status-monitor/1", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return HttpResponse(response.status, response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read() if exc.fp else b"")


def _timed(run: Callable[[], str]) -> ProbeResult:
    started = time.monotonic()
    try:
        error = run()
    except TimeoutError:
        error = "timeout"
    except (urllib.error.URLError, OSError) as exc:
        error = "timeout" if "timed out" in str(exc) else "connection_error"
    except ValueError:
        error = "bad_response"
    return ProbeResult(error == "", error, time.monotonic() - started)


def _json(body: bytes) -> dict | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def chat_without_account(api_url: str, monitor_token: str, post: HttpPost = http_post) -> ProbeResult:
    """One anonymous chat turn through POST /v1/anonymous/chat/stream (JSON reply)."""
    def run() -> str:
        payload = {"client_chat_id": str(uuid.uuid4()), "client_message_id": str(uuid.uuid4()),
                   "anonymous_id": MONITOR_ANONYMOUS_ID, "plaintext_message": CHAT_PROMPT,
                   "system_language": "en"}
        response = post(f"{api_url}/v1/anonymous/chat/stream", payload,
                        {MONITOR_HEADER: monitor_token} if monitor_token else {}, CHAT_TIMEOUT_S)
        if response.status != 200:
            return f"http_{response.status}"
        data = _json(response.body)
        if data is None or data.get("status") != "completed":
            return "not_completed"
        return "" if str(data.get("assistant") or "").strip() else "empty_answer"
    return _timed(run)


def _ask_answer(data: dict | None) -> str:
    if data is None:
        return ""
    body = data.get("data", data) if data.get("success", True) else {}
    choices = body.get("choices") if isinstance(body, dict) else None
    if not choices:
        return ""
    answer = str((choices[0].get("message") or {}).get("content") or "")
    return "" if answer.startswith(EMPTY_REPLY_PLACEHOLDER) else answer


def chat_with_account(api_url: str, api_key: str, post: HttpPost = http_post) -> ProbeResult:
    """One signed-in chat turn through the developer API (POST /v1/apps/ai/skills/ask)."""
    def run() -> str:
        response = post(f"{api_url}/v1/apps/ai/skills/ask",
                        {"messages": [{"role": "user", "content": CHAT_PROMPT}], "stream": False},
                        {"Authorization": f"Bearer {api_key}"}, CHAT_TIMEOUT_S)
        if response.status != 200:
            return f"http_{response.status}"
        answer = _ask_answer(_json(response.body)).strip()
        if not answer:
            return "empty_answer"
        return "error_answer" if answer.startswith("Error:") else ""
    return _timed(run)


def skill_web_search(api_url: str, api_key: str, post: HttpPost = http_post) -> ProbeResult:
    """A signed-in chat whose answer needs the web search skill."""
    def run() -> str:
        response = post(f"{api_url}/v1/apps/ai/skills/ask",
                        {"messages": [{"role": "user", "content": SEARCH_PROMPT}], "stream": False},
                        {"Authorization": f"Bearer {api_key}"}, SKILL_TIMEOUT_S)
        if response.status != 200:
            return f"http_{response.status}"
        data = _json(response.body)
        answer = _ask_answer(data).strip()
        if not answer or answer.startswith("Error:"):
            return "empty_answer" if not answer else "error_answer"
        return "" if skill_was_used(data, "web", "search") else "skill_not_used"
    return _timed(run)


def skill_was_used(data: dict | None, app_id: str, skill_id: str) -> bool:
    """True when the ask response reports a run of ``app_id.skill_id``."""
    if data is None:
        return False
    text = json.dumps(data.get("data", data))
    return f'"app_id": "{app_id}"' in text and f'"skill_id": "{skill_id}"' in text


GOOGLE_CLOUD_INCIDENTS_URL = "https://status.cloud.google.com/incidents.json"


def google_cloud_status(url: str = GOOGLE_CLOUD_INCIDENTS_URL) -> ProbeResult:
    """Google Cloud's official incident feed: fails only on an open Gemini/Vertex AI outage."""
    def run() -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "openmates-status-monitor/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            incidents = json.load(response)
        if not isinstance(incidents, list):
            return "unexpected_feed"
        return "provider_outage" if google_cloud_ai_incident_open(incidents) else ""
    return _timed(run)


def google_cloud_ai_incident_open(incidents: list[dict]) -> bool:
    """True when Google Cloud lists an unresolved high-severity Gemini/Vertex AI incident."""
    for incident in incidents:
        if incident.get("end") or incident.get("severity") != "high":
            continue
        products = " ".join(str(p.get("title", "")) for p in incident.get("affected_products") or [])
        if "Gemini" in products or "Vertex AI" in products:
            return True
    return False
