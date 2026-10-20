"""Opt-in real-provider qualification of the production daily copy recovery chain.

Public retrieval fixtures keep evidence identical. Native HTTP receipts and every
draft, usage record and Jev review persist after each card. No user/pool writes.
Injected failures are reported separately and never count as provider outages.
"""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import logging
import math
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai.models import AsyncModels

from backend.apps.ai.daily_inspiration import config, decisions, generator, video_processor, wiki_generator, writer
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.scripts.benchmark_daily_inspiration_models import HOLDOUT_SOURCES, POLICY_CASES, GROUNDING_CASES, assess
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.shared.providers.wikipedia.wikipedia_api import WikipediaTopic

SOURCES = HOLDOUT_SOURCES + [
    {"id": "rainbow-es", "language": "es", "title": "Cómo se forma un arcoíris", "wiki_title": "Arcoíris",
     "description": "Un arcoíris aparece cuando la luz del Sol entra en gotas de agua. La luz se refracta, se refleja dentro de las gotas y sale separada en colores."},
    {"id": "snow-ja", "language": "ja", "title": "雪の結晶ができる仕組み", "wiki_title": "雪の結晶",
     "description": "雪の結晶は雲の中で水蒸気が氷になることで成長します。氷の結晶構造によって六角形の形が生まれます。温度や水蒸気の量によって形が変わります。"},
]


async def run(options):
    root = Path(options.output_dir)
    root.mkdir(parents=True, exist_ok=False)
    manager = SecretsManager()
    await manager.initialize()
    rows, native, jev, accounting, controls = [], [], [], [], []
    original_send = httpx.AsyncClient.send
    original_google = AsyncModels.generate_content
    started = time.perf_counter()
    source_hashes = {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                     for m in (config, decisions, generator, video_processor, wiki_generator, writer)}
    source_hashes["benchmark"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def save():
        (root / "receipt.json").write_text(json.dumps({"rows": rows, "native_http": native,
            "jev": jev, "decision_accounting": accounting, "controls": controls,
            "source_sha256": source_hashes, "policy_version": decisions.POLICY_VERSION}, ensure_ascii=False, indent=2))

    async def send(client, request, *args, **kwargs):
        response = await original_send(client, request, *args, **kwargs)
        if request.url.host in {"api.inceptionlabs.ai", "generativelanguage.googleapis.com"}:
            await response.aread()
            native.append({"host": request.url.host, "status": response.status_code,
                           "request": json.loads(request.content), "response": response.json()})
            save()
            if (request.url.host == "api.inceptionlabs.ai" and response.status_code < 400
                    and response.json().get("model") != "mercury-3"):
                raise ValueError("Unexpected observed Mercury model")
        return response

    async def google_generate(client, **kwargs):
        response = await original_google(client, **kwargs)
        native.append({"transport": "google_sdk", "requested_model": kwargs.get("model"),
                       "response": response.model_dump(mode="json", exclude_none=True)})
        if not (response.model_version or "").startswith("gemini-3.5-flash-lite"):
            raise ValueError("Unexpected observed Gemini model version")
        save()
        return response

    class RecordedJev:
        def __init__(self, **kwargs):
            self.client = JevDecisionClient(**{**kwargs, "max_retries": 0, "accounting": accounting})

        async def evaluate(self, **kwargs):
            response = await self.client.evaluate(**kwargs)
            jev.append({"request": kwargs, "response": response.model_dump()})
            return response

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(httpx.AsyncClient, "send", send))
            stack.enter_context(patch.object(AsyncModels, "generate_content", google_generate))
            stack.enter_context(patch.object(decisions, "JevDecisionClient", RecordedJev))
            for cases, field in ((POLICY_CASES, "policy"), (GROUNDING_CASES, "grounding")):
                candidates = ([{"title": title, "description": description} for _, title, description, _ in cases]
                              if field == "policy" else [{"title": "Educational explanation", "description": desc,
                                  "assistant_response": copy} for _, desc, copy, _ in cases])
                offset = len(jev)
                await decisions.review_candidates(candidates, manager)
                if len(jev) != offset + 1:
                    raise RuntimeError("Editorial controls unavailable")
                answers = jev[-1]["response"]["answers"]
                for index, case in enumerate(cases):
                    controls.append({"kind": field, "case": case[0], "expected": case[-1],
                                     "actual": answers[f"candidate_{index:03d}_{field}"]["choice"]})

            cases = [(source, kind, "natural") for source in SOURCES for kind in ("video", "wiki")]
            cases += [(SOURCES[0], "video", "force_second_attempt"),
                      (SOURCES[2], "wiki", "force_gemini_fallback")]
            for source, kind, scenario in cases:
                if time.perf_counter() - started > 900:
                    raise RuntimeError("15-minute benchmark bound reached")
                row = {"case": source["id"], "language": source["language"], "type": kind,
                       "scenario": scenario, "source": source, "attempts": []}
                rows.append(row)
                before, account_start, native_start = time.perf_counter(), len(accounting), len(native)

                async def call(**kwargs):
                    attempt = {"requested_model": kwargs["model_id"], "request": kwargs["message_history"]}
                    row["attempts"].append(attempt)
                    forced = scenario == "force_gemini_fallback" and len(row["attempts"]) <= 2
                    forced |= scenario == "force_second_attempt" and len(row["attempts"]) == 1
                    if forced:
                        attempt["injected"] = True
                        return SimpleNamespace(arguments=None, error_message="Injected transport failure")
                    stamp = time.perf_counter()
                    result = await call_preprocessing_llm(**kwargs)
                    attempt.update(seconds=time.perf_counter() - stamp, result=result.model_dump())
                    save()
                    return result

                async def search(**_kwargs):
                    return {"results": [{"url": "https://www.youtube.com/watch?v=bioLight001", "title": source["title"],
                        "description": source["description"], "video": {"creator": "Independent Science Teacher"}}]}

                async def enrich(candidates, *_args, **_kwargs):
                    return [{**item, "published_at": "2026-01-01T00:00:00Z", "made_for_kids": False} for item in candidates]

                async def wiki_search(*_args, **_kwargs):
                    return [SimpleNamespace(key=source["wiki_title"], disambiguation=False)]

                async def validate(*_args, **_kwargs):
                    return [WikipediaTopic(topic=source["wiki_title"], wiki_title=source["wiki_title"], description=source["description"])]

                async def summary(*_args, **_kwargs):
                    return {"title": source["wiki_title"], "description": source["description"], "extract": source["description"]}

                with ExitStack() as fixtures:
                    for module, name, replacement in [(video_processor, "search_videos", search),
                            (video_processor, "_enrich_with_youtube", enrich),
                            (generator, "call_preprocessing_llm", call), (wiki_generator, "call_preprocessing_llm", call),
                            (wiki_generator, "search_wikipedia_titles", wiki_search),
                            (wiki_generator, "batch_validate_topics", validate), (wiki_generator, "fetch_page_summary", summary)]:
                        fixtures.enter_context(patch.object(module, name, replacement))
                    items = (await generator.generate_inspirations("public-benchmark", 1, [source["title"]], manager,
                                language=source["language"]) if kind == "video" else
                             await wiki_generator.generate_wiki_inspirations([source["title"]], manager, count=1,
                                language=source["language"]))
                row.update(items=[item.model_dump() for item in items], seconds=time.perf_counter() - before,
                           native_http=native[native_start:], decision_attempts=accounting[account_start:])
                row["issues"] = assess(items, source["language"]) if source["language"] in {"en", "de", "es"} else ([] if items else ["no_accepted_card"])
                row["format_check_scope"] = "word_based_heuristics" if source["language"] in {"en", "de", "es"} else "structural_only"
                save()
                print(json.dumps({key: row[key] for key in ("case", "type", "scenario", "issues", "seconds")}), flush=True)
    finally:
        save()
        await manager.aclose()

    natural = [row for row in rows if row["scenario"] == "natural"]
    latencies = sorted(row["seconds"] for row in natural)
    usage = [attempt["result"].get("usage_telemetry") or {} for row in rows for attempt in row["attempts"] if "result" in attempt]
    actual_attempts = [attempt for row in rows for attempt in row["attempts"] if not attempt.get("injected")]
    word_checked = [row for row in natural if row["format_check_scope"] == "word_based_heuristics"]
    summary = {"natural_cases": len(natural), "admitted": sum(bool(row["items"]) for row in natural),
               "finite_checks_pass": sum(not row["issues"] for row in word_checked),
               "finite_checks_total": len(word_checked),
               "p50_seconds": statistics.median(latencies), "p95_seconds": latencies[math.ceil(.95 * len(latencies)) - 1],
               "natural_attempt_models": [attempt["requested_model"] for row in natural for attempt in row["attempts"]],
               "controls_correct": sum(row["expected"] == row["actual"] for row in controls), "controls_total": len(controls),
               "known_supplier_usd": sum(item.get("supplier_cost_usd") or 0 for item in usage)
                   + sum((item.get("input_tokens") or 0) * .042 / 1e6 for item in accounting),
               "usage_complete": len(usage) == len(actual_attempts) and all(item.get("supplier_cost_complete") for item in usage)
                   and all(item.get("input_tokens") is not None for item in accounting),
               "mercury_http_statuses": [item["status"] for item in native if item.get("host") == "api.inceptionlabs.ai"],
               "mercury_observed_models": sorted({item["response"].get("model", "") for item in native
                    if item.get("host") == "api.inceptionlabs.ai" and item["status"] < 400}),
               "injected_cases": [{"scenario": row["scenario"], "admitted": bool(row["items"]),
                    "models": [attempt["requested_model"] for attempt in row["attempts"]]} for row in rows if row["scenario"] != "natural"]}
    (root / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", required=True)
    options = parser.parse_args()
    if options.execute:
        logging.basicConfig(level=logging.ERROR)
        asyncio.run(run(options))
    else:
        print("Dry run: 12 natural cards in EN/DE/ES/JA; two separately labeled injected-recovery cases; 20 Jev controls.")
