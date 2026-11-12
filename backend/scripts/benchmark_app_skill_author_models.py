#!/usr/bin/env python3
# contract-test-file: tooling
"""
Purpose: Benchmark candidate author LLMs for the three app skills that share one author model list
    (videos.generate composed video, images.modify, vector images).
Architecture: Runs inside the api container. For each model x skill x case it calls the skill's author
    (compose_video / author_modification / author_svg) with models=(<one ref>,) so there is no fallback,
    then records success, attempts, author token usage, cost (regular and introductory tariff, read from
    backend/providers/*.yml), wall time and sandbox seconds, and writes the outputs.
Data sources: Synthetic pictures drawn with Pillow; no user data. Prices from the provider yml files.
Tests: Manual benchmark - writes <out>/<skill>/<case>/<model>/ (mp4+thumbnail+source, png+program, svg),
    <out>/results.json and <out>/results.md. Costs real inference and sandbox minutes.
Usage: docker exec api python /app/backend/scripts/benchmark_app_skill_author_models.py --out /tmp/author-bench
    [--models openai/gpt-6.1-sol,google/gemini-4-argon] [--skills video,modify,vector] [--cases v1,m2,s1]
    (copied script: PYTHONPATH=/app python /tmp/benchmark_app_skill_author_models.py ...)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import yaml
from PIL import Image, ImageDraw, ImageFont

from backend.apps.images.modify_author import ModifyAuthorError, author_modification
from backend.apps.images.modify_program import ModifyInputError, prepare_inputs
from backend.apps.images.vector_author import InvalidSvgError, VectorAuthorError, author_svg
from backend.apps.ai.utils.llm_utils import AllServersFailedError
from backend.apps.videos.composed.author import compose_video
from backend.apps.videos.composed.models import (
    ComposedInput, ComposedInputError, ComposedRequest, ComposeFailure,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager

MODELS = ("openai/gpt-6.1-sol", "google/gemini-3.8-flash", "google/gemini-4-argon", "google/gemini-4-carbon")
CASES = {"video": ("v1", "v2", "v3"), "modify": ("m1", "m2"), "vector": ("s1", "s2")}
# Failures an author can raise for a bad or unavailable model; anything else is a script bug and propagates.
EXPECTED_ERRORS = (ComposeFailure, ComposedInputError, ModifyAuthorError, ModifyInputError, VectorAuthorError,
                   InvalidSvgError, AllServersFailedError, TimeoutError, OSError)
PROVIDER_DIR = Path(sys.modules["backend"].__path__[0]) / "providers"
FONT = "DejaVuSans-Bold.ttf"

V1_INSTRUCTION = ("8 second product teaser: title 'OpenMates', then each picture full-screen with a caption "
                  "('Your AI team' for the first, 'Private by design' for the second), then an outro "
                  "'Try it today'.")
V2_INSTRUCTION = ("12 second news recap: an opening title 'Weekly recap', then one scene per picture, each showing "
                  "the picture with the headline and sentence of the matching source text, then an outro "
                  "'More next week'.")
V3_INSTRUCTION = ("6 second animated title 'Quarterly results' that fades in, followed by an animated bar chart of "
                  "four values: Q1 12, Q2 18, Q3 9, Q4 25, bars growing one after another with value labels.")
V2_SOURCES = (("Solar farm opens", "A new solar farm with 40 megawatts started delivering power to the town."),
              ("Library extends hours", "The central library now stays open until 10 pm on weekdays."),
              ("Bike lanes finished", "The city completed 12 kilometres of protected bike lanes this month."))
M1_INSTRUCTION = ("Place the small logo picture in the bottom-right corner of the photo with a margin of 5 percent "
                  "of the photo width. Keep the photo otherwise unchanged.")
M2_INSTRUCTION = "Crop the picture to a square (centered), increase the contrast, and add a 20 px white border."
S1_PROMPT = "A simple flat icon of a paper plane, one accent colour on a plain background, centered."
S2_PROMPT = ("A small infographic titled '3 steps' with three numbered circles (1, 2, 3) connected by a line, each "
             "with a label: 'Write', 'Review', 'Publish'.")


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _picture(size: tuple[int, int], colours: tuple[str, str], label: str) -> bytes:
    image = Image.new("RGB", size, colours[0])
    draw = ImageDraw.Draw(image)
    width, height = size
    for step in range(0, max(size), 60):
        draw.line([(step, 0), (0, step)], fill=colours[1], width=18)
    draw.ellipse([width * 0.3, height * 0.25, width * 0.7, height * 0.75], fill="white", outline=colours[1], width=12)
    font = ImageFont.truetype(FONT, max(24, height // 8))
    draw.text((width / 2, height / 2), label, fill=colours[1], font=font, anchor="mm")
    return _png(image)


def _photo(size: tuple[int, int]) -> bytes:
    """Photo-like landscape: sky gradient, sun, hills and a lake."""
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / height
        draw.line([(0, y), (width, y)], fill=(int(120 + 100 * mix), int(170 + 50 * mix), int(235 - 40 * mix)))
    draw.ellipse([width * 0.7, height * 0.1, width * 0.82, height * 0.1 + width * 0.12], fill=(255, 235, 170))
    draw.polygon([(0, height * 0.7), (width * 0.25, height * 0.4), (width * 0.5, height * 0.7)], fill=(70, 105, 80))
    draw.polygon([(width * 0.3, height * 0.7), (width * 0.62, height * 0.35), (width, height * 0.7)], fill=(55, 90, 70))
    draw.rectangle([0, height * 0.7, width, height], fill=(60, 110, 150))
    return _png(image)


def _logo(side: int) -> bytes:
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, side - 4, side - 4], fill=(245, 158, 11, 255), outline=(30, 30, 30, 255), width=6)
    draw.text((side / 2, side / 2), "OM", fill="white", font=ImageFont.truetype(FONT, side // 3), anchor="mm")
    return _png(image)


def _video_input(index: int, data: bytes, size: tuple[int, int], title: str, text: str = "") -> ComposedInput:
    return ComposedInput(name=f"input-{index}.png", content=data, mime_type="image/png", width=size[0],
                         height=size[1], title=title, kind="search_result" if text else "image", text=text)


def _video_request(case: str) -> ComposedRequest:
    first = _picture((1600, 1000), ("#1d4ed8", "#f59e0b"), "TEAM")
    second = _picture((900, 1200), ("#065f46", "#f43f5e"), "LOCK")
    if case == "v1":
        inputs = (_video_input(1, first, (1600, 1000), "Team illustration"),
                  _video_input(2, second, (900, 1200), "Privacy illustration"))
        return ComposedRequest(V1_INSTRUCTION, "16:9", 8, inputs)
    if case == "v2":
        third = _picture((1200, 800), ("#7c2d12", "#fde047"), "CITY")
        pictures = ((first, (1600, 1000)), (second, (900, 1200)), (third, (1200, 800)))
        inputs = tuple(_video_input(i + 1, data, size, V2_SOURCES[i][0],
                                    f"Title: {V2_SOURCES[i][0]}\nDescription: {V2_SOURCES[i][1]}")
                       for i, (data, size) in enumerate(pictures))
        return ComposedRequest(V2_INSTRUCTION, "16:9", 12, inputs)
    return ComposedRequest(V3_INSTRUCTION, "16:9", 6, ())


@dataclass
class Prices:
    regular: tuple[float, float]  # USD per million input / output tokens
    intro: tuple[float, float]


def _load_prices(ref: str) -> Optional[Prices]:
    provider, model = ref.split("/", 1)
    document = yaml.safe_load((PROVIDER_DIR / f"{provider}.yml").read_text(encoding="utf-8"))
    for entry in document.get("models", []):
        if entry.get("id") != model:
            continue
        costs = entry["costs"]
        regular = (costs["input_per_million_token"]["price"], costs["output_per_million_token"]["price"])
        intro = regular
        for temporary in entry.get("temporary_prices", []):
            cost = temporary["costs"]
            intro = (cost["input_per_million_token"]["price"], cost["output_per_million_token"]["price"])
            break
        return Prices(regular, intro)
    return None


def _cost(prices: Optional[Prices], tokens_in: int, tokens_out: int) -> dict[str, Optional[float]]:
    if prices is None:
        return {"regular": None, "intro": None}
    return {key: round((tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000, 5)
            for key, rates in (("regular", prices.regular), ("intro", prices.intro))}


class UsageMeter:
    """Wraps call_main_llm_stream and sums the provider-reported usage per call.

    The authors read ``input_tokens``/``output_tokens`` from usage chunks, which Google's chunks do not carry
    (they report prompt/candidates/thoughts counts), so the benchmark counts both shapes itself.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    async def stream(self, **kwargs: Any):
        from backend.apps.ai.utils.llm_utils import call_main_llm_stream

        self.calls += 1
        last: Any = None
        async for chunk in call_main_llm_stream(**kwargs):
            if not isinstance(chunk, str) and (hasattr(chunk, "input_tokens") or hasattr(chunk, "prompt_token_count")):
                last = chunk
            yield chunk
        if last is None:
            return
        if getattr(last, "input_tokens", None) is not None:
            self.tokens_in += int(last.input_tokens or 0)
            self.tokens_out += int(getattr(last, "output_tokens", 0) or 0)
        else:
            self.tokens_in += int(last.prompt_token_count or 0)
            self.tokens_out += int((last.candidates_token_count or 0) + (getattr(last, "thoughts_token_count", 0) or 0))


async def _run_video(case: str, ref: str, out: Path, secrets: SecretsManager, meter: UsageMeter) -> dict[str, Any]:
    video = await compose_video(_video_request(case), secrets_manager=secrets, task_id=f"bench-{case}",
                                models=(ref,), stream_fn=meter.stream)
    (out / "video.mp4").write_bytes(video.mp4)
    (out / "thumbnail.png").write_bytes(video.thumbnail_png)
    (out / video.filename).write_text(video.source, encoding="utf-8")
    return {"attempts": video.attempts, "sandbox_seconds": [round(v, 1) for v in video.sandbox_seconds]}


async def _run_modify(case: str, ref: str, out: Path, secrets: SecretsManager, meter: UsageMeter) -> dict[str, Any]:
    if case == "m1":
        pictures = [("input-1.png", _photo((1600, 1000)), "pixel"), ("input-2.png", _logo(300), "pixel")]
        instructions, requirements = M1_INSTRUCTION, ["The logo is in the bottom-right corner with a visible margin."]
    else:
        pictures = [("input-1.png", _photo((1600, 1000)), "pixel")]
        instructions = M2_INSTRUCTION
        requirements = ["The picture is square.", "The contrast is increased.", "A 20 px white border surrounds it."]
    for name, data, _ in pictures:
        (out / name).write_bytes(data)
    result = await author_modification(task_id=f"bench-{case}", instructions=instructions,
                                       inputs=prepare_inputs(pictures), requirements=requirements,
                                       secrets_manager=secrets, models=(ref,), stream_fn=meter.stream)
    (out / "output.png").write_bytes(result.image)
    (out / "program.py").write_text(result.program, encoding="utf-8")
    return {"attempts": result.attempts, "review": result.review_status,
            "sandbox_seconds": [round(v, 1) for v in result.sandbox_seconds]}


async def _run_vector(case: str, ref: str, out: Path, secrets: SecretsManager, meter: UsageMeter) -> dict[str, Any]:
    prompt = S1_PROMPT if case == "s1" else S2_PROMPT
    result = await author_svg(task_id=f"bench-{case}", prompt=prompt, secrets_manager=secrets, models=(ref,), stream_fn=meter.stream)
    (out / "output.svg").write_text(result.svg, encoding="utf-8")
    return {"attempts": result.attempts, "review": result.review_status,
            "sandbox_seconds": [round(v, 1) for v in result.sandbox_seconds]}


RUNNERS: dict[str, Callable[[str, str, Path, SecretsManager, UsageMeter], Awaitable[dict[str, Any]]]] = {
    "video": _run_video, "modify": _run_modify, "vector": _run_vector,
}


async def _one(skill: str, case: str, ref: str, out: Path, secrets: SecretsManager) -> dict[str, Any]:
    folder = out / skill / case / ref.replace("/", "_")
    folder.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"skill": skill, "case": case, "model": ref}
    started = time.monotonic()
    meter = UsageMeter()
    try:
        detail = await RUNNERS[skill](case, ref, folder, secrets, meter)
        row.update(status="ok", **detail)
    except EXPECTED_ERRORS as exc:
        row.update(status="fail", error=f"{type(exc).__name__}: {exc}"[-1500:], attempts=None)
    row.update(llm_calls=meter.calls, tokens_in=meter.tokens_in, tokens_out=meter.tokens_out)
    row["seconds"] = round(time.monotonic() - started, 1)
    row["cost_usd"] = _cost(_load_prices(ref), row["tokens_in"], row["tokens_out"])
    print(json.dumps({k: v for k, v in row.items() if k != "error"}), flush=True)
    if row["status"] == "fail":
        print(f"  error: {row['error'][:300]}", flush=True)
    return row


def _table(rows: list[dict[str, Any]]) -> str:
    lines = ["| model | skill | case | result | attempts | tokens in/out | cost regular / intro USD | seconds | sandbox s |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        cost = row["cost_usd"]
        lines.append(f"| {row['model']} | {row['skill']} | {row['case']} | {row['status']} | {row['attempts']} | "
                     f"{row['tokens_in']}/{row['tokens_out']} | {cost['regular']} / {cost['intro']} | "
                     f"{row['seconds']} | {sum(row.get('sandbox_seconds', [])) or '-'} |")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/author-bench")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--skills", default="video,modify,vector")
    parser.add_argument("--cases", default="")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted_cases = {item for item in args.cases.split(",") if item}
    secrets = SecretsManager()
    await secrets.initialize()
    # A rerun keeps the rows already measured and only runs what is missing.
    results_file = out / "results.json"
    rows: list[dict[str, Any]] = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else []
    done = {(row["skill"], row["case"], row["model"]) for row in rows}
    try:
        for skill in args.skills.split(","):
            for case in CASES[skill]:
                if wanted_cases and case not in wanted_cases:
                    continue
                for ref in args.models.split(","):
                    if (skill, case, ref) in done:
                        continue
                    rows.append(await _one(skill, case, ref, out, secrets))
                    (out / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    finally:
        await secrets.aclose()
    table = _table(rows)
    (out / "results.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
