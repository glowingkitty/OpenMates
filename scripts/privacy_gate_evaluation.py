"""Offline, synthetic-only GLiNER2.5-Decide -> native Privacy Filter evaluation.

This benchmark never activates a product detector. Checkpoints and dependencies
must be prepared separately; inference denies network syscalls. A negative gate
decision is evaluated as a potential privacy miss, not accepted as authorization.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import resource
import threading
import time

from privacy_filter_evaluation import CppRedactor, deny_network_syscalls, load_json, score


TASKS = {"privacy": {
    "sensitive_information": "Contains private names, residential addresses, personal contact or financial details, passwords or secret credentials.",
    "ordinary_content": "Public facts or ordinary code, documentation, identifiers and technical output without private personal information or secrets.",
}}


def text_windows(text, tokenizer, size=256, overlap=32):
    """Scan every subword, including code with long non-whitespace strings."""
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                        truncation=False)["offset_mapping"]
    if not offsets:
        return [(0, len(text), text)]
    windows = []
    for start in range(0, len(offsets), size - overlap):
        end = min(start + size, len(offsets))
        first = 0 if start == 0 else offsets[start][0]
        last = len(text) if end == len(offsets) else offsets[end - 1][1]
        windows.append((first, last, text[first:last]))
        if end == len(offsets):
            break
    return windows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--opf-model", type=Path, required=True)
    p.add_argument("--opf-library", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--profile", choices=["float32", "int8"], default="float32")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--long-tokens", type=int, default=2048)
    p.add_argument("--boundary-only", action="store_true",
                   help="Run only a synthetic name crossing a gate-window boundary")
    p.add_argument("--max-rss-gib", type=float, default=8)
    args = p.parse_args()
    if args.threads < 1 or args.long_tokens < 512 or args.max_rss_gib <= 0:
        p.error("resource bounds must be positive; long tokens must be >=512")
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:args.threads])
    os.nice(10)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      OMP_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS=str(args.threads),
                      TOKENIZERS_PARALLELISM="false")
    isolation = deny_network_syscalls()
    started = time.perf_counter()
    import psutil
    import torch
    from gliner2 import AutoExtractor
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    process = psutil.Process()
    peak = 0
    stop = threading.Event()

    def monitor():
        nonlocal peak
        while not stop.wait(0.1):
            rss = process.memory_info().rss
            peak = max(peak, rss)
            if rss > args.max_rss_gib * 2**30:
                print("Stopping this evaluation: RSS limit exceeded", flush=True)
                os._exit(75)

    threading.Thread(target=monitor, daemon=True).start()
    before_load = process.memory_info().rss
    t = time.perf_counter()
    model = AutoExtractor.from_pretrained(str(args.checkpoint), map_location="cpu", local_files_only=True)
    load_seconds = time.perf_counter() - t
    parameters = sum(x.numel() for x in model.parameters())
    quantize_seconds = 0
    if args.profile == "int8":
        torch.backends.quantized.engine = "qnnpack"
        t = time.perf_counter()
        torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
        quantize_seconds = time.perf_counter() - t
        gc.collect()
    model.eval()
    fixtures = load_json(args.fixtures)
    baseline = load_json(args.baseline)
    tokenizer = model.processor.tokenizer
    result = {"profile": args.profile, "threads": args.threads, "tasks": TASKS,
              "network_isolation": isolation, "torch": torch.__version__,
              "parameter_count": parameters, "gate_load_seconds": load_seconds,
              "quantize_seconds": quantize_seconds, "rss_imported_bytes": before_load,
              "rss_gate_loaded_bytes": process.memory_info().rss,
              "rss_gate_load_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "quality": [], "long": []}

    def save():
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    def gate(text):
        rows = []
        for first, last, chunk in text_windows(text, tokenizer):
            t = time.perf_counter()
            with torch.inference_mode():
                prediction = model.classify_text(chunk, TASKS, include_confidence=True)["privacy"]
            rows.append({"start": first, "end": last, "prediction": prediction,
                         "seconds": time.perf_counter() - t})
        return rows

    def route(rows, confidence=None):
        # Only confident ordinary decisions permit skipping in a conservative policy.
        return any(r["prediction"].get("label") != "ordinary_content" or (
            confidence is not None and r["prediction"].get("confidence", 0) < confidence) for r in rows)

    if args.boundary_only:
        seed = "const buildStatus = 'ready';\n" * 100
        offsets = tokenizer(seed, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
        for count in range(230, 270):
            text = seed[:offsets[count][0]] + "\n// Our customer Amina Okafor lives at her home: 42 Maple Avenue, Bristol BS1 4QA.\n"
            name_start = text.index("Amina Okafor")
            name_end = name_start + len("Amina Okafor")
            first_end = text_windows(text, tokenizer)[0][1]
            if name_start < first_end < name_end:
                break
        else:
            raise RuntimeError("Could not construct a name crossing the first window")
        rows = gate(text)
        result["boundary"] = {"name_start": name_start, "name_end": name_end,
                              "first_window_end": first_end, "windows": rows,
                              "route_strict": route(rows), "route_conservative_080": route(rows, 0.8),
                              "gate_seconds": sum(r["seconds"] for r in rows)}
        result["total_seconds"] = time.perf_counter() - started
        result["rss_os_peak_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        stop.set()
        save()
        print("complete boundary " + str(args.output), flush=True)
        return

    print("gate loaded " + json.dumps({k: v for k, v in result.items() if k not in ("quality", "long", "tasks")}), flush=True)
    for fixture in fixtures:
        rows = gate(fixture["text"])
        row = {"id": fixture["id"], "expected_sensitive": bool(fixture["expected"]),
               "windows": rows, "gate_seconds": sum(r["seconds"] for r in rows),
               "route_strict": route(rows), "route_conservative_080": route(rows, 0.8),
               "route_conservative_090": route(rows, 0.9)}
        result["quality"].append(row)
        save()
        print(f"case {fixture['id']}: {row['gate_seconds']:.3f}s, route={row['route_strict']}", flush=True)
    result["rss_gate_warm_bytes"] = process.memory_info().rss

    t = time.perf_counter()
    opf = CppRedactor(args.opf_library, args.opf_model, args.threads, 4096)
    result["opf_load_seconds_with_gate"] = time.perf_counter() - t
    result["rss_both_loaded_bytes"] = process.memory_info().rss
    direct, gated, conservative = [], [], []
    for fixture, row in zip(fixtures, result["quality"]):
        t = time.perf_counter()
        spans = opf.redact(fixture["text"])["detected_spans"]
        row["opf_seconds"] = time.perf_counter() - t
        # Evidence does not publish literal synthetic vendor-key formats.
        row["opf_ranges"] = [{k: s[k] for k in ("label", "start", "end")} for s in spans]
        direct.append({"id": row["id"], "spans": row["opf_ranges"]})
        gated.append({"id": row["id"], "spans": row["opf_ranges"] if row["route_strict"] else []})
        conservative.append({"id": row["id"], "spans": row["opf_ranges"] if row["route_conservative_080"] else []})
    baseline_by_id = {r["id"]: r for r in baseline}
    for name, rows in [("direct_opf", direct), ("strict_gate_opf", gated), ("conservative080_gate_opf", conservative)]:
        raw = score(fixtures, rows)
        combined = score(fixtures, [{"id": r["id"], "spans": r["spans"] + baseline_by_id[r["id"]]["spans"]} for r in rows])
        result[name + "_summary"] = {k: raw[k] for k in ["expected_values", "content_hidden", "fully_hidden", "by_category"]}
        result[name + "_with_regex_summary"] = {k: combined[k] for k in ["expected_values", "content_hidden", "fully_hidden", "by_category"]}
    result["false_negative_inputs"] = [r["id"] for r in result["quality"] if r["expected_sensitive"] and not r["route_strict"]]
    result["false_positive_inputs"] = [r["id"] for r in result["quality"] if not r["expected_sensitive"] and r["route_strict"]]
    result["rss_both_warm_bytes"] = process.memory_info().rss

    # Scan full long inputs: no head-only shortcut or confidence-winning merge.
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    code = 'export function normalizeBuildStatus(value) { return String(value ?? "pending").trim(); }\n'
    ids = enc.encode(code * (args.long_tokens // 10 + 1))[:args.long_tokens]
    clean = enc.decode(ids)
    long_inputs = [("clean-code", clean),
                   ("sensitive-at-tail", clean + '\n// Contact our customer Amina Okafor at her home: 42 Maple Avenue, Bristol BS1 4QA.\n')]
    for name, text in long_inputs:
        rows = gate(text)
        t = time.perf_counter()
        spans = opf.redact(text)["detected_spans"]
        opf_seconds = time.perf_counter() - t
        row = {"id": name, "bytes": len(text.encode()), "opf_tokens": len(enc.encode(text)),
               "gliner_subwords": len(tokenizer(text, add_special_tokens=False)["input_ids"]),
               "windows": rows, "gate_seconds": sum(r["seconds"] for r in rows),
               "route_strict": route(rows), "route_conservative_080": route(rows, 0.8),
               "opf_seconds": opf_seconds, "opf_ranges": [{k:s[k] for k in ("label", "start", "end")} for s in spans]}
        result["long"].append(row)
        save()
        print("long " + json.dumps({k:v for k,v in row.items() if k not in ("windows", "opf_ranges")}), flush=True)

    # Explicitly release native model ownership; contrast warm-only with both resident.
    import ctypes
    opf.lib.pf_free.argtypes = [ctypes.c_void_p]
    opf.lib.pf_free(opf.ctx)
    del opf
    gc.collect()
    libc = ctypes.CDLL("libc.so.6")
    libc.malloc_trim(0)
    result["rss_after_opf_unload_bytes"] = process.memory_info().rss
    result["rss_sampled_peak_bytes"] = peak
    result["rss_os_peak_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["total_seconds"] = time.perf_counter() - started
    stop.set()
    save()
    print("complete " + str(args.output), flush=True)


if __name__ == "__main__":
    main()
