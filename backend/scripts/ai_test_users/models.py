"""Model calls for AI test users: persona steps, the screenshot judge and the Jev check.

Reuses the Browse model layer (`BrowserModels`): the persona's next step goes
through its metered text helper (DeepSeek via Together when that route is
enabled, otherwise Gemini 3.8 Flash), the judge is one Gemini 3.8 Flash call
with screenshots, and every finding is checked once more by Jev against its
screenshot. All calls are admitted against a hard USD cap before they start
and accounted with the provider catalog's supplier tariff afterwards.
"""

from __future__ import annotations

import base64
import io
import json
import time
from datetime import date
from decimal import Decimal
from typing import Any

from backend.shared.providers.browser_models import BrowserModelError, BrowserModels, parse_browser_json
from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.shared.python_utils.billing_utils import snapshot_model_tariff

STEP_INPUT_CHARS = 60_000
STEP_OUTPUT_TOKENS = 1_200
JUDGE_OUTPUT_TOKENS = 6_000
JUDGE_IMAGES = 14
FINDING_KEEP_SCORE = 0.5
ACTION_KINDS = {"click", "type", "select", "scroll", "wait", "back", "goto", "wait_for_reply", "finish"}

STEP_INSTRUCTIONS = """You are a simulated real person testing the OpenMates web app (an AI assistant with chats,
apps, skills, focus modes, embeds and settings). Stay in character as the persona below and work towards its goals
the way that person would: natural wording in the persona's language, typos allowed, follow-up questions when an
answer is unclear, opening results/embeds/fullscreen views, trying the obvious buttons.

Each turn you get the current page (url, title, visible text, interactive controls with ids) plus your history.
Return ONLY JSON:
{"thought": "<one sentence>",
 "actions": [ {"kind": "click", "target": "<control id>"} | {"kind": "type", "target": "<id>", "text": "...", "submit": true|false}
   | {"kind": "select", "target": "<id>", "value": "..."} | {"kind": "scroll", "delta": <pixels, negative = up>}
   | {"kind": "wait"} | {"kind": "back"} | {"kind": "goto", "url": "<https url on the allowed app host>"}
   | {"kind": "wait_for_reply"} | {"kind": "finish"} ],
 "notes": [ {"category": "error|broken_ui|odd_ui|unreadable_data|wrong_data|mismatch|slow|bad_answer|other",
   "what": "<what exactly you saw, quoting the page>"} ],
 "goal": <index of the goal you are working on>}

Rules:
- At most 4 actions; a click that opens something new must be the last action. `goto` must be the only action.
- To send a chat message, type into the message editor with "submit": true, then use {"kind":"wait_for_reply"} as
  the next turn's only action so the answer can finish streaming.
- Notes: only real problems a user would notice, each quoting what is on the page. No notes when all is fine.
  Look for: error messages, broken or overlapping layout, raw/unformatted values (ISO dates, JSON, placeholders,
  i18n keys like "chat.foo.bar"), wrong or made-up facts, links/buttons that do not match the result they belong
  to, answers that ignore the question, wrong language, endless loading.
- Never log out, delete the account, change security settings, buy or pay for anything, submit an issue report,
  or share/publish anything publicly. Deleting your own test chats is fine.
- Work through every goal in order before finishing; the step budget is shown as step/max_steps. After sending a
  message, always wait for the reply and read it before moving on. Use {"kind":"finish"} only when all goals are
  done, when you are truly stuck after trying alternatives, or in the last two steps of the budget."""

# Intended app behavior that first runs reported as defects (20 Nov 2026). The judge and Jev get it as context.
EXPECTED_BEHAVIOR = (
    "Without 'Stay logged in' a page reload signs the user out and clears the local chat store (privacy by design). "
    "The 'Log in to keep chatting' prompt and login modal that follow such a reload are expected. "
    "After a gift card signup the app opens Settings > Gift Cards by itself (known, tracked separately). "
    "Dates and years are judged against the run date given as `today`, not against your training data. "
    "/settings is not a page; settings open as a drawer."
)

JUDGE_INSTRUCTIONS = """You are a strict QA judge reviewing one simulated user's session in the OpenMates web app.
You get the persona and its goals, a step transcript (actions, page text excerpts, timings, the persona's own notes,
browser console errors, failed HTTP calls, blocked external links) and screenshots labelled with their step number.

Check against this list: (1) error messages or crashes; (2) broken, overlapping, cut-off or odd UI, also on phone
size; (3) unreadable data such as raw ISO date strings, JSON, null/undefined, untranslated i18n keys; (4) wrong or
made-up data; (5) mismatches, e.g. a bus result whose booking button belongs to a different operator, a link pointing to a
different provider or item than shown; (6) slow responses (answer not complete after ~30 s, or spinners that never end);
(7) bad answers: ignores the question, wrong language, unhelpful, hallucinated; (8) inconsistencies between screens.

Only report what the evidence shows. A finding must cite the step number and quote or describe the exact screen
content. Do not report the masked (blacked-out) login screens, the test account's synthetic data, or harness
limits (blocked external links are expected; judge only WHERE they pointed). Never report the session ending,
goals left unfinished, or the simulated user's own choices (not waiting, clicking Send after pressing Enter) as app
defects; judge only what the app showed or did. Do not report the expected behavior listed under `expected_behavior`
in the payload. Return ONLY JSON:
{"findings": [{"title": "<short, specific, product wording>", "category": "<one of the 8 above>",
  "severity": "high|medium|low", "step": <int>, "evidence": "<quote/description>", "expected": "<what should happen>",
  "surface": "<area of the app, e.g. chat answer, travel embed, settings>"}],
 "goal_outcomes": [{"goal": "<text>", "achieved": true|false, "why": "<short>"}],
 "answer_quality": [{"step": <int of the step where the answer was read>, "question": "<the user's question, short>",
   "score": <1-5, 5 = helpful, correct, complete, natural>, "why": "<short>"}],
 "demo_candidate": {"is_candidate": true|false, "why": "<short>", "steps": [<step numbers of the chat>]},
 "summary": "<two sentences>"}

answer_quality has one row for every assistant answer the simulated user read. demo_candidate.is_candidate is true
only when one chat is helpful, correct, natural and visually good enough to show on the landing page; otherwise false."""

JEV_FINDING_QUESTION = (
    "Is the reported problem clearly visible in the screenshot or directly supported by the quoted step "
    "evidence, and is it a real defect of the web app rather than expected behavior (see expected_behavior and today), test-harness masking, "
    "or the judge misreading the screen? Answer no when the evidence is missing or ambiguous."
)


def fit_for_jev(image: str) -> str:
    """Jev accepts JPEGs of 280..1568 px per side and at most 1 MiB; phone screenshots are taller."""
    from PIL import Image

    picture = Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB")
    scale = min(1.0, 1568 / max(picture.size))
    if scale < 1.0:
        picture = picture.resize((max(280, int(picture.width * scale)), max(280, int(picture.height * scale))))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=70)
    return base64.b64encode(buffer.getvalue()).decode()


def normalize_judge_extras(verdict: dict[str, Any]) -> dict[str, Any]:
    """Validate the judge's `answer_quality` rows and `demo_candidate` verdict (absent = empty / not a candidate)."""
    rows = []
    for row in verdict.get("answer_quality") or []:
        score = row.get("score") if isinstance(row, dict) else None
        if isinstance(score, (int, float)) and not isinstance(score, bool) and 1 <= score <= 5:
            step = row.get("step")
            rows.append({
                "step": step if isinstance(step, int) else None,
                "question": str(row.get("question", ""))[:200],
                "score": int(round(score)),
                "why": str(row.get("why", ""))[:400],
            })
    demo = verdict.get("demo_candidate")
    demo = demo if isinstance(demo, dict) else {}
    verdict["answer_quality"] = rows
    verdict["demo_candidate"] = {
        "is_candidate": demo.get("is_candidate") is True,
        "why": str(demo.get("why", ""))[:400],
        "steps": [s for s in demo.get("steps") or [] if isinstance(s, int)][:40],
    }
    return verdict


class BudgetExceeded(RuntimeError):
    """The next paid call would pass this persona's hard harness budget."""


class TesterModels(BrowserModels):
    """`BrowserModels` with a hard per-persona cap and the tester's own prompts."""

    def __init__(self, secrets_manager: Any, *, cap_usd: Decimal) -> None:
        super().__init__(secrets_manager, before_attempt=self._admit, after_attempt=self._accounted)
        self.cap = cap_usd
        self.reserved: dict[str, Decimal] = {}

    async def _admit(self, model: str, host: str, bound: Decimal) -> str:
        committed = self.cost + sum(self.reserved.values(), Decimal(0))
        if committed + bound > self.cap:
            raise BudgetExceeded(f"harness budget {self.cap} USD reached")
        call_id = f"{model}:{time.monotonic_ns()}"
        self.reserved[call_id] = bound
        return call_id

    async def _accounted(self, call_id: str, _attempt: dict[str, Any]) -> None:
        self.reserved.pop(call_id, None)

    async def persona_step(self, context: dict[str, Any]) -> dict[str, Any]:
        """One persona turn; one repair attempt for malformed JSON."""
        for attempt in range(2):
            try:
                reply = await self.text_call(
                    context,
                    instructions=STEP_INSTRUCTIONS,
                    output_tokens=STEP_OUTPUT_TOKENS,
                    max_input_chars=STEP_INPUT_CHARS,
                    purpose=None,
                )
            except BrowserModelError:
                if attempt:
                    raise
                context = {**context, "previous_reply_rejected": "not valid JSON; return only the JSON object"}
                continue
            if isinstance(reply, dict) and isinstance(reply.get("actions"), list):
                return reply
            context = {**context, "previous_reply_rejected": "missing actions list"}
        raise BrowserModelError("The browser planner returned an invalid plan.")

    async def vision_json(
        self, *, instructions: str, payload: dict[str, Any], images: list[tuple[str, str]], output_tokens: int
    ) -> Any:
        """One admitted Gemini 3.8 Flash call with labelled JPEG screenshots (same accounting as text_call)."""
        from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

        provider, model, host = "google", "gemini-3.8-flash", "google_ai_studio"
        config = self.catalog.get_model_pricing(provider, model, inference_host=host)
        if not config:
            raise BrowserModelError("The browser model tariff is unavailable.")
        tariff = snapshot_model_tariff(config)
        tariff["bill_reasoning_tokens"] = True
        text = json.dumps(payload, ensure_ascii=False)
        model_ref = provider + "/" + model
        # Each image is bounded at ~1,300 tokens at the default media resolution.
        bound = self.quote(model_ref, host, len((text + instructions).encode()) + 1_400 * len(images) + 4096, output_tokens)
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for label, image in images:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}})
        call_id = await self.admit(model_ref, host, bound)
        started = time.monotonic()
        try:
            response = await invoke_google_ai_studio_chat_completions(
                task_id="ai_test_user_judge",
                model_id=model,
                messages=[{"role": "system", "content": instructions}, {"role": "user", "content": content}],
                secrets_manager=self.secrets,
                temperature=0.1,
                max_tokens=output_tokens,
                stream=False,
                thinking_level="LOW",
                request_attempts=1,
                request_timeout_seconds=120,
            )
        except BaseException:
            await self.account(call_id=call_id, model=model_ref, host=host, usage={}, elapsed=time.monotonic() - started)
            raise
        native = response.usage
        usage = native.model_dump() if callable(getattr(native, "model_dump", None)) else dict(native or {})
        if response.success and usage.get("cache_read_input_tokens") is None:
            usage["cache_read_input_tokens"] = 0
        try:
            usage = normalize_provider_usage(
                usage, model_id=model_ref, provider_kind="google", inference_host=host, tariff_snapshot=tariff
            ).to_bucket()
        except (ValueError, TypeError):
            usage = {"tariff_snapshot": tariff}
        await self.account(call_id=call_id, model=model_ref, host=host, usage=usage, elapsed=time.monotonic() - started)
        return parse_browser_json(response.direct_message_content)

    async def judge(self, payload: dict[str, Any], images: list[tuple[str, str]]) -> dict[str, Any]:
        result = await self.vision_json(
            instructions=JUDGE_INSTRUCTIONS, payload=payload, images=images[:JUDGE_IMAGES], output_tokens=JUDGE_OUTPUT_TOKENS
        )
        if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
            raise BrowserModelError("The browser text helper returned invalid JSON.")
        return normalize_judge_extras(result)

    async def jev_supports(self, finding: dict[str, Any], step: dict[str, Any] | None, screenshot: str | None) -> float:
        """Jev's probability that the finding is real, given its step and screenshot."""
        state = {
            "today": date.today().isoformat(),
            "expected_behavior": EXPECTED_BEHAVIOR,
            "finding": {k: finding.get(k) for k in ("title", "category", "evidence", "expected", "surface")},
            "step": {k: (step or {}).get(k) for k in ("url", "title", "page_text", "actions", "events", "reply_timing")},
        }
        result = await self.decision(
            state,
            {"real_defect": {"type": "noul", "instructions": JEV_FINDING_QUESTION}},
            screenshot=fit_for_jev(screenshot) if screenshot else None,
        )
        return float(result.answers["real_defect"].noul)
