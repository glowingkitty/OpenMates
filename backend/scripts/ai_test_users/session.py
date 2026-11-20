#!/usr/bin/env python3
"""One AI test user session: E2B browser, real dev web app, transcript, video, judged findings.

Dev test tooling. Started by the host orchestrator `scripts/ai_test_users.py`,
one process per persona, inside the api container (Vault secrets, provider
catalog and the Browse model layer live there):

  docker exec -i api python /app/backend/scripts/ai_test_users/session.py < job.json

The job arrives on stdin only (it holds the throwaway account's values; they are
never written to disk or logged, and reach the sandbox only as form input). Output goes to `job.output_dir` inside the container
(screenshots, `video.webm`, `transcript.json`, `result.json`); the host copies
it out and removes it.

Flow: create one disposable E2B sandbox from the Browse template, stop its
prebooted runtime, upload `driver.py` plus a copy of the Browse runtime,
launch Chromium with the persona's device profile, sign up a throwaway account
(Inbox Kitten code), redeem the gift card, then loop persona steps (observe, model step, act) within the step, time and
budget limits. Afterwards one Gemini judge call reviews transcript and
screenshots, Jev checks each finding, kept findings are filed through the web
Report issue form, and the account is deleted before the sandbox is killed (in
every case). Target may be dev or prod; the worker refuses to run unless
SERVER_ENVIRONMENT=development.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from pathlib import Path
import re
import secrets as token_source
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
import wave

import httpx
from e2b.exceptions import SandboxException

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling models.py, also from a copied trial checkout
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402 - container path setup
import flows  # noqa: E402
from transcript import render as render_transcript  # noqa: E402
from models import (  # noqa: E402
    ACTION_KINDS,
    FINDING_KEEP_SCORE,
    EXPECTED_BEHAVIOR,
    BudgetExceeded,
    TesterModels,
)
from backend.shared.providers.browser_models import BrowserModelError  # noqa: E402
from backend.shared.providers.typesafe.client import DecisionProviderError  # noqa: E402
from backend.shared.providers.e2b_browser import (  # noqa: E402
    PRIVATE_NETWORKS,
    RUNTIME_PYTHON,
    BrowserUnavailable,
    E2BBrowser,
)
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNTIME_SOURCE = Path("/app/backend/shared/providers/web_browse_runtime.py")
SANDBOX_HOME = "/home/user/.ai-tester"
DRIVER_PORT = 8766
USD_PER_VCPU_SECOND = Decimal("0.000014")  # https://e2b.dev/pricing (as scripts/e2b_dev_capacity.py)
USD_PER_GIB_SECOND = Decimal("0.0000045")
ELEVENLABS_USD_PER_CHAR = Decimal("0.0002")  # upper bound for flash TTS characters
HISTORY_TURNS = 14
PAGE_TEXT_CHARS = 14_000
STEP_TEXT_CHARS = 2_500
BLOCKED_LABEL = re.compile(
    r"\b(log ?out|sign ?out|abmelden|delete (my )?account|konto löschen|buy|purchase|checkout|pay\b|kaufen|bezahlen|"
    r"subscribe|report (an )?issue|submit report|problem melden|disable 2fa|reset password|change password|"
    r"make public|publish)\b",
    re.I,
)


GIFT_HASH = re.compile(r"#gift-card=\S*")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


async def voice_clip(secrets: SecretsManager, text: str) -> bytes:
    """Speak `text` once with ElevenLabs into a 16 kHz mono WAV for Chromium's fake microphone."""
    from backend.apps.audio.assistant_speech.voice_profiles import ASSISTANT_VOICE_PROVIDER_IDS

    key = await secrets.get_secret("kv/data/providers/elevenlabs", "api_key")
    if not key:
        raise BrowserUnavailable("The voice clip provider is unavailable.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ASSISTANT_VOICE_PROVIDER_IDS['george']}",
            params={"output_format": "pcm_16000"},
            headers={"xi-api-key": key},
            json={"text": text, "model_id": "eleven_flash_v2_5"},
        )
    response.raise_for_status()
    silence = b"\x00\x00" * 16000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16000)
        clip.writeframes(silence + response.content + silence * 3)
    return buffer.getvalue()


def compact_controls(observation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for control in observation.get("controls", []):
        row = {k: control[k] for k in ("id", "role", "kind") if control.get(k) is not None}
        row["label"] = (control.get("label") or "")[:90]
        if control.get("value"):
            row["value"] = control["value"][:120]
        if control.get("href"):
            row["href"] = control["href"][:160]
        if control.get("options"):
            row["options"] = [o.get("label") for o in control["options"][:15]]
        if not control.get("in_viewport"):
            row["offscreen"] = True
        rows.append(row)
    return rows


class Session:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job
        self.mode = flows.validate_job(job)
        self.persona = job["persona"]
        self.out = Path(job["output_dir"])
        self.out.mkdir(parents=True, exist_ok=True)
        self.transcript: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {"persona": self.persona["id"] if self.persona else None, "mode": self.mode, "status": "started", "findings": []}
        self.sandbox = None
        self.provider: dict[str, Any] | None = None
        self.browser: E2BBrowser | None = None
        self.sandbox_started: float | None = None
        self.cpu, self.memory_mb = 2, 4096
        self.extra_cost = Decimal(0)
        self.screenshots: dict[int, str] = {}
        self.inbox = None
        self.account_created = False

    # --- sandbox ------------------------------------------------------------
    async def create_sandbox(self, api_key: str) -> None:
        from e2b import Sandbox

        template = os.environ.get("E2B_BROWSE_TEMPLATE")
        if not template:
            raise BrowserUnavailable("The E2B browser template has not been configured.")
        lifetime = int(self.job["max_minutes"] * 60 + 600)
        self.sandbox = await asyncio.to_thread(
            Sandbox.create,
            template,
            api_key=api_key,
            request_timeout=30,
            envs={"PLAYWRIGHT_BROWSERS_PATH": "/opt/openmates-browser/browsers"},
            timeout=lifetime,
            network={"deny_out": PRIVATE_NETWORKS, "allow_public_traffic": False},
            metadata={"openmates_ai_test_user_run": self.job["run_id"], "persona": self.persona["id"] if self.persona else "delete_only"},
        )
        self.sandbox_started = time.monotonic()
        info = await asyncio.to_thread(self.sandbox.get_info)
        self.cpu = getattr(info, "cpu_count", None) or 2
        self.memory_mb = getattr(info, "memory_mb", None) or 4096
        sandbox = self.sandbox
        token = token_source.token_urlsafe(32)
        # The prebooted Browse runtime holds its own Chromium; the tester uses a separate one.
        await asyncio.to_thread(sandbox.commands.run, "pkill -f '[.]openmates-browse/server[.]py' || true", timeout=10)
        await asyncio.to_thread(sandbox.commands.run, f"mkdir -p {SANDBOX_HOME}", timeout=10)
        await asyncio.to_thread(sandbox.files.write, f"{SANDBOX_HOME}/config.json", json.dumps({"token": token}))
        await asyncio.to_thread(sandbox.files.write, f"{SANDBOX_HOME}/browse_runtime.py", RUNTIME_SOURCE.read_text())
        await asyncio.to_thread(sandbox.files.write, f"{SANDBOX_HOME}/driver.py", (HERE / "driver.py").read_text())
        if self.persona and self.persona.get("voice_text"):
            clip = await voice_clip(self.secrets, self.persona["voice_text"])
            self.extra_cost += ELEVENLABS_USD_PER_CHAR * len(self.persona["voice_text"])
            await asyncio.to_thread(sandbox.files.write, f"{SANDBOX_HOME}/voice.wav", clip)
        await asyncio.to_thread(
            sandbox.commands.run,
            f"{RUNTIME_PYTHON} {SANDBOX_HOME}/driver.py > {SANDBOX_HOME}/driver.log 2>&1",
            background=True,
            timeout=0,
        )
        self.provider = {
            "token": token,
            "traffic_access_token": sandbox.traffic_access_token,
            "rpc_url": f"https://{sandbox.get_host(DRIVER_PORT)}",
        }
        for _ in range(80):
            try:
                await self.rpc({"operation": "ping"}, timeout=3)
                return
            except BrowserUnavailable:
                await asyncio.sleep(0.5)
        raise BrowserUnavailable("The tester driver did not start.")

    async def rpc(self, body: dict[str, Any], timeout: float = 40) -> dict[str, Any]:
        """One driver call. A refused operation (HTTP 409) keeps the driver's error class and detail,
        which the shared Browse client drops; login and signup bodies never echo their detail."""
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            try:
                response = await client.post(
                    self.provider["rpc_url"], json=body,
                    headers={"Authorization": "Bearer " + self.provider["token"],
                             "e2b-traffic-access-token": self.provider["traffic_access_token"]},
                )
            except httpx.HTTPError as exc:
                raise BrowserUnavailable(f"driver unreachable ({type(exc).__name__})") from None
        if response.status_code == 409:
            try:
                error = response.json()
            except ValueError:
                error = {}
            raise BrowserUnavailable(f"{body.get('operation')}: {error.get('error')}: {error.get('detail', '')}"[:300])
        if response.status_code != 200:
            raise BrowserUnavailable(f"{body.get('operation')}: driver HTTP {response.status_code}")
        result = response.json()
        if not isinstance(result, dict):
            raise BrowserUnavailable(f"{body.get('operation')}: invalid driver reply")
        return result

    async def driver_error(self) -> str:
        try:
            log_text = await asyncio.to_thread(self.sandbox.files.read, f"{SANDBOX_HOME}/driver.log")
        except Exception as exc:  # diagnostics only; the original failure is reported either way
            return f"driver log unavailable: {type(exc).__name__}"
        return log_text[-1500:]

    def e2b_cost(self) -> Decimal:
        if self.sandbox_started is None:
            return Decimal(0)
        seconds = Decimal(str(time.monotonic() - self.sandbox_started))
        return seconds * (self.cpu * USD_PER_VCPU_SECOND + Decimal(self.memory_mb) / 1024 * USD_PER_GIB_SECOND)

    # --- persona loop -----------------------------------------------------------
    def save_screenshot(self, step: int, image: str | None) -> str | None:
        if not image:
            return None
        name = f"step-{step:03d}.jpg"
        (self.out / name).write_bytes(base64.b64decode(image))
        self.screenshots[step] = image
        return name

    def stop_reason(self, models: TesterModels, started: float, step: int) -> str | None:
        if step >= self.job["max_steps"]:
            return "max_steps"
        if time.monotonic() - started > self.job["max_minutes"] * 60:
            return "max_minutes"
        if os.path.exists(self.job["stop_file"]):
            return "stopped_by_orchestrator"
        if self.e2b_cost() > Decimal(str(self.job["e2b_cap_usd"])):
            return "e2b_budget"
        if models.cost + self.extra_cost > models.cap:
            return "harness_budget"
        return None

    def page_context(self, observation: dict[str, Any]) -> dict[str, Any]:
        text = observation.get("document_text") or observation.get("text") or ""
        return {
            "url": GIFT_HASH.sub("", str(observation.get("url") or "")),
            "title": observation.get("title"),
            "dialogs": observation.get("dialogs"),
            "visible_text": (observation.get("text") or "")[:4000],
            "page_text": text[:PAGE_TEXT_CHARS],
            "page_text_truncated": len(text) > PAGE_TEXT_CHARS,
            "scroll": observation.get("scroll"),
            "controls": compact_controls(observation),
        }

    def sanitize(self, actions: list[Any], observation: dict[str, Any]) -> tuple[list[dict], list[str]]:
        controls = {c["id"]: c for c in observation.get("controls", [])}
        allowed_hosts = set(self.job["allowed_hosts"])
        kept, refused = [], []
        for raw in actions[:4]:
            if not isinstance(raw, dict) or raw.get("kind") not in ACTION_KINDS:
                refused.append("unknown action")
                continue
            target = controls.get(str(raw.get("target"))) if "target" in raw else None
            if raw["kind"] in ("click", "type", "select") and target is None:
                refused.append(f"unknown target {raw.get('target')}")
                continue
            probe = " ".join(str(v) for v in ((target or {}).get("label"), (target or {}).get("href")) if v)
            if raw["kind"] == "click" and BLOCKED_LABEL.search(probe):
                refused.append(f"blocked by test policy: {probe[:80]}")
                continue
            if raw["kind"] == "goto":
                host = re.sub(r"^https://([^/]+).*$", r"\1", str(raw.get("url", "")))
                if host not in allowed_hosts:
                    refused.append("goto outside the app")
                    continue
            kept.append(raw)
        return kept, refused

    async def run_steps(self, models: TesterModels) -> str:
        started = time.monotonic()
        observation = await self.rpc({"operation": "observe"})
        step = 0
        while True:
            reason = self.stop_reason(models, started, step)
            if reason:
                return reason
            step += 1
            events = (await self.rpc({"operation": "events"})).get("events", [])
            shot = self.save_screenshot(step, observation.get("screenshot"))
            page = self.page_context(observation)
            context = {
                "persona": {k: self.persona.get(k) for k in ("name", "description", "language", "device_label")},
                "goals": self.persona["goals"],
                "step": step,
                "max_steps": self.job["max_steps"],
                "elapsed_minutes": round((time.monotonic() - started) / 60, 1),
                "history": self.history[-HISTORY_TURNS:],
                "browser_events_since_last_step": events[-15:],
                "page": page,
            }
            t0 = time.monotonic()
            try:
                reply = await models.persona_step(context)
            except BudgetExceeded:
                return "harness_budget"
            think_seconds = round(time.monotonic() - t0, 1)
            actions, refused = self.sanitize(reply.get("actions") or [], observation)
            entry: dict[str, Any] = {
                "step": step,
                "at_seconds": round(t0 - started, 1),
                "url": page["url"],
                "title": page["title"],
                "page_text": page["page_text"][:STEP_TEXT_CHARS],
                "screenshot": shot,
                "thought": str(reply.get("thought", ""))[:400],
                "actions": actions,
                "refused": refused,
                "notes": [n for n in reply.get("notes") or [] if isinstance(n, dict)][:5],
                "events": events[-25:],
                "goal": reply.get("goal"),
                "model_seconds": think_seconds,
            }
            outcome = ""
            if any(a["kind"] == "finish" for a in actions):
                entry["outcome"] = "finished"
                self.transcript.append(entry)
                return "persona_finished"
            if any(a["kind"] == "wait_for_reply" for a in actions):
                timing = await self.rpc({"operation": "wait_for_text", "timeout": 120}, timeout=150)
                entry["reply_timing"] = timing
                outcome = f"waited {timing['seconds']}s for the reply (settled={timing['settled']})"
                observation = await self.rpc({"operation": "observe"})
            elif actions:
                try:
                    stepped = await self.rpc(
                        {"operation": "step", "observation_id": observation.get("observation_id"),
                         "actions": actions, "screenshot": True},
                        timeout=60,
                    )
                    outcome = "; ".join(
                        f"{r.get('kind')} {r.get('target', '')} {r.get('outcome')} {r.get('detail', '')}".strip()
                        for r in stepped["results"]
                    )
                    observation = stepped["observation"]
                except BrowserUnavailable:
                    # The page changed after the observation (SPA route update) or a target went stale.
                    outcome = "rejected: page changed before the action; observing again"
                    observation = await self.rpc({"operation": "observe"})
            else:
                outcome = "no executable action" + (f" ({'; '.join(refused)})" if refused else "")
                observation = await self.rpc({"operation": "observe"})
            entry["outcome"] = outcome
            self.transcript.append(entry)
            self.history.append({
                "step": step,
                "thought": entry["thought"],
                "did": [{k: a.get(k) for k in ("kind", "target", "text", "url") if a.get(k) is not None} for a in actions],
                "outcome": outcome[:300],
                "refused": refused,
            })

    # --- judge --------------------------------------------------------------------
    def judge_images(self) -> list[tuple[str, str]]:
        important = [e["step"] for e in self.transcript if e.get("notes") or e.get("reply_timing")
                     or any(ev.get("kind") in ("page_error", "http_error", "popup_opened",
                                               "external_navigation_blocked") for ev in e.get("events", []))]
        steps = sorted(self.screenshots)
        chosen: list[int] = []
        for step in important + steps[::max(1, len(steps) // 6)] + steps[-1:]:
            if step in self.screenshots and step not in chosen:
                chosen.append(step)
        chosen = sorted(chosen[:14])
        return [(f"Screenshot of step {s}:", self.screenshots[s]) for s in chosen]

    async def judge(self, models: TesterModels) -> None:
        payload = {
            "today": datetime.now(UTC).date().isoformat(),
            "expected_behavior": EXPECTED_BEHAVIOR,
            "persona": self.persona,
            "device": self.persona.get("device_label"),
            "transcript": [
                {k: e.get(k) for k in ("step", "at_seconds", "url", "thought", "actions", "outcome", "notes",
                                       "events", "reply_timing", "page_text", "refused")}
                for e in self.transcript
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False)
        while len(raw) > 400_000 and payload["transcript"]:
            for entry in payload["transcript"]:
                entry["page_text"] = (entry.get("page_text") or "")[: max(200, len(entry.get("page_text") or "") // 2)]
            raw = json.dumps(payload, ensure_ascii=False)
        verdict = await models.judge(payload, self.judge_images())
        by_step = {e["step"]: e for e in self.transcript}
        for finding in verdict.get("findings", [])[:20]:
            if not isinstance(finding, dict):
                continue
            step = finding.get("step") if isinstance(finding.get("step"), int) else None
            image = self.screenshots.get(step) if step else None
            try:
                score = await models.jev_supports(finding, by_step.get(step), image)
            except BudgetExceeded:
                score = None
            except (BrowserModelError, DecisionProviderError) as exc:
                log(f"jev check failed: {exc}")
                finding["jev_error"] = str(exc)[:200]
                score = None
            finding["id"] = len(self.result["findings"])
            finding["jev_score"] = score
            finding["kept"] = score is None or score >= FINDING_KEEP_SCORE
            finding["screenshot"] = f"step-{step:03d}.jpg" if image else None
            self.result["findings"].append(finding)
        self.result["goal_outcomes"] = verdict.get("goal_outcomes", [])
        self.result["summary"] = verdict.get("summary", "")
        self.result["answer_quality"] = verdict.get("answer_quality", [])
        self.result["demo_candidate"] = verdict.get("demo_candidate", {"is_candidate": False, "why": "", "steps": []})

    # --- main -------------------------------------------------------------------------
    async def run(self) -> dict[str, Any]:
        if os.environ.get("SERVER_ENVIRONMENT") != "development":
            raise SystemExit("AI test users run only on the development server.")
        self.secrets = SecretsManager()
        await self.secrets.initialize()
        api_key = await get_e2b_api_key_async(self.secrets)
        self.browser = E2BBrowser(api_key)
        if self.mode == "delete_only":
            return await self.run_delete_only()
        models = TesterModels(self.secrets, cap_usd=Decimal(str(self.job["harness_cap_usd"])))
        wall = time.monotonic()
        result = self.result
        result.update(target=self.job.get("target"), reports=[], deletion={"status": "skipped", "error": None})
        try:
            await self.create_sandbox(api_key)
            result["sandbox_ready_seconds"] = round(time.monotonic() - wall, 1)
            await self.rpc({
                "operation": "launch",
                "url": self.job["app_url"],
                "allowed_hosts": self.job["allowed_hosts"],
                "device": self.persona["device"],
                "locale": self.persona.get("locale", "en-US"),
                "timezone": self.persona.get("timezone", "Europe/Berlin"),
                "voice": bool(self.persona.get("voice_text")),
            }, timeout=60)
            signed_up = await flows.run_stage(result, "signup", lambda: flows.signup(self), self)
            if signed_up:
                log(f"{self.persona['id']}: signed up")
                carded = await flows.run_stage(result, "gift_card", lambda: flows.gift_card(self), self)
                result["status"] = await self.run_steps(models) if carded else "gift_card_failed"
                log(f"{self.persona['id']}: steps ended ({result['status']})")
                if self.transcript:
                    try:
                        await self.judge(models)
                        await flows.submit_reports(self)
                    except (BudgetExceeded, BrowserModelError, DecisionProviderError, ValueError, BrowserUnavailable) as exc:
                        result["judge_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    result["credits_end"] = (await self.rpc({"operation": "credits"}, timeout=60))["credits"]
                except BrowserUnavailable:
                    result["credits_end"] = None
            else:
                result["status"] = "signup_failed"
        except (BrowserUnavailable, BrowserModelError, KeyError, SandboxException, httpx.HTTPError) as exc:
            result["status"] = "harness_error"
            result["error"] = f"{type(exc).__name__}: {exc}"
            if self.sandbox is not None:
                result["driver_log_tail"] = await self.driver_error()
        finally:
            if self.sandbox is not None and self.provider is not None:
                await flows.delete_stage(self)
                try:
                    finished = await self.rpc({"operation": "finish"}, timeout=60)
                    for index, path in enumerate(finished.get("videos", [])):
                        data = await asyncio.to_thread(self.sandbox.files.read, path, format="bytes")
                        (self.out / ("video.webm" if index == 0 else f"video-{index}.webm")).write_bytes(bytes(data))
                except BrowserUnavailable as exc:
                    result["video_error"] = str(exc)
            result["e2b"] = {
                "seconds": round(time.monotonic() - self.sandbox_started, 1) if self.sandbox_started else 0,
                "cpu": self.cpu,
                "memory_mb": self.memory_mb,
                "usd": float(round(self.e2b_cost(), 4)),
            }
            if self.sandbox is not None:
                await asyncio.to_thread(self.sandbox.kill)
        result.update(
            steps=len(self.transcript),
            wall_seconds=round(time.monotonic() - wall, 1),
            harness_usd=float(round(models.cost + self.extra_cost, 4)),
            model_calls=[{k: a.get(k) for k in ("model", "host", "cost_usd", "elapsed_seconds")} for a in models.attempts],
            reply_timings=[e["reply_timing"] for e in self.transcript if e.get("reply_timing")],
        )
        (self.out / "transcript.json").write_text(json.dumps(self.transcript, ensure_ascii=False, indent=1))
        (self.out / "transcript.md").write_text(render_transcript(result, self.persona, self.transcript, str(self.job.get("target"))))
        (self.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        return result

    async def run_delete_only(self) -> dict[str, Any]:
        """Retry the deletion of an account whose earlier deletion failed: login, delete, no persona, no video."""
        wall = time.monotonic()
        result = self.result
        result.update(target=self.job.get("target"), deletion={"status": "failed", "error": None})
        try:
            await self.create_sandbox(await get_e2b_api_key_async(self.secrets))
            await self.rpc({
                "operation": "launch", "url": self.job["app_url"], "allowed_hosts": self.job["allowed_hosts"],
                "device": self.job.get("device") or {"width": 1280, "height": 800}, "locale": "en-US", "timezone": "Europe/Berlin", "voice": False,
            }, timeout=60)
            result["deletion"] = {"status": await flows.login_and_delete(self), "error": None}
            result["status"] = "delete_only_done"
        except flows.STAGE_ERRORS + (SandboxException,) as exc:
            result["status"] = "harness_error"
            result["deletion"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            if self.sandbox is not None:
                result["driver_log_tail"] = await self.driver_error()
        finally:
            result["e2b"] = {
                "seconds": round(time.monotonic() - self.sandbox_started, 1) if self.sandbox_started else 0,
                "cpu": self.cpu, "memory_mb": self.memory_mb, "usd": float(round(self.e2b_cost(), 4)),
            }
            if self.sandbox is not None:
                await asyncio.to_thread(self.sandbox.kill)
        result.update(steps=0, wall_seconds=round(time.monotonic() - wall, 1), harness_usd=0.0)
        (self.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        return result



def main() -> int:
    job = json.loads(sys.stdin.read())
    result = asyncio.run(Session(job).run())
    print(json.dumps({k: result.get(k) for k in ("persona", "status", "steps", "harness_usd", "e2b", "error", "deletion")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
