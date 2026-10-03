"""Bounded, offline CPU evaluation of OpenAI Privacy Filter; synthetic inputs only.

Install OpenAI's pinned runtime into a separate venv and pass a downloaded original
checkpoint. This script never installs packages, downloads models or contacts APIs.
The baseline JSON is produced by privacy_filter_regex_baseline.mjs using the CLI
test loader. Results include synthetic input/output, not real Project content.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import socket
import statistics
import threading
import time


def load_json(path):
    """Assemble synthetic credential fixtures; never store complete vendor keys."""
    return json.loads(path.read_text(), object_hook=lambda value: (
        "".join(value["synthetic_parts"]) if set(value) == {"synthetic_parts"} else value))


def deny_network_syscalls():
    """Apply a Linux process-local filter, inherited by subsequently created threads."""
    import ctypes as c
    lib = c.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.argtypes = [c.c_uint32]
    lib.seccomp_init.restype = c.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [c.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = c.c_int
    lib.seccomp_rule_add.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.c_uint]
    lib.seccomp_load.argtypes = [c.c_void_p]
    lib.seccomp_release.argtypes = [c.c_void_p]
    ctx = lib.seccomp_init(0x7FFF0000)  # allow other syscalls
    if not ctx:
        raise OSError("seccomp initialization failed")
    try:
        for name in (b"socket", b"socketpair", b"connect"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            if syscall < 0 or lib.seccomp_rule_add(ctx, 0x00050001, syscall, 0):
                raise OSError("seccomp network rule failed")
        if lib.seccomp_load(ctx):
            raise OSError("seccomp network filter failed")
    finally:
        lib.seccomp_release(ctx)
    try:
        socket.socket()
    except PermissionError:
        return "linux-seccomp-socket-denied"
    raise RuntimeError("network isolation self-check failed")


class CppRedactor:
    """Evaluation-only FFI for the pinned third-party runtime; UTF-8 offsets."""

    def __init__(self, library, checkpoint, threads, context):
        import ctypes as c
        self.c = c
        self.lib = c.CDLL(str(library))

        class Entity(c.Structure):
            _fields_ = [("start", c.c_int32), ("end", c.c_int32),
                        ("score", c.c_float), ("label", c.c_char_p)]

        self.Entity = Entity
        self.lib.pf_load.argtypes = [c.c_char_p, c.c_char_p, c.c_int]
        self.lib.pf_load.restype = c.c_void_p
        self.lib.pf_last_error.argtypes = [c.c_void_p]
        self.lib.pf_last_error.restype = c.c_char_p
        self.lib.pf_set_window.argtypes = [c.c_void_p, c.c_int32]
        self.lib.pf_classify.argtypes = [c.c_void_p, c.c_char_p, c.c_size_t, c.c_float,
                                       c.POINTER(c.POINTER(Entity)), c.POINTER(c.c_size_t)]
        self.lib.pf_classify.restype = c.c_int
        self.lib.pf_entities_free.argtypes = [c.POINTER(Entity), c.c_size_t]
        self.ctx = self.lib.pf_load(os.fsencode(checkpoint), b"cpu", threads)
        error = self.lib.pf_last_error(self.ctx)
        if error:
            raise RuntimeError(error.decode())
        self.lib.pf_set_window(self.ctx, context)

    def redact(self, text):
        c = self.c
        raw = text.encode("utf-8")
        entities = c.POINTER(self.Entity)()
        count = c.c_size_t()
        if self.lib.pf_classify(self.ctx, raw, len(raw), 0.0, c.byref(entities), c.byref(count)):
            raise RuntimeError(self.lib.pf_last_error(self.ctx).decode())
        try:
            spans = []
            for index in range(count.value):
                entity = entities[index]
                spans.append({"label": entity.label.decode(),
                              "start": len(raw[:entity.start].decode()),
                              "end": len(raw[:entity.end].decode()),
                              "text": raw[entity.start:entity.end].decode(), "score": entity.score})
            return {"text": text, "detected_spans": spans}
        finally:
            self.lib.pf_entities_free(entities, count)


def score(fixtures, rows):
    """Full-value concealment matters more than mere overlap for privacy."""
    by_id = {row["id"]: row for row in rows}
    groups = {}
    details = []
    false_positive_cases = []
    for fixture in fixtures:
        spans = by_id[fixture["id"]]["spans"]
        covered = {i for span in spans for i in range(span["start"], span["end"])}
        for label, value in fixture["expected"]:
            start = fixture["text"].index(value)
            positions = set(range(start, start + len(value)))
            # Separately count addresses returned as multiple complete pieces,
            # with only a comma/whitespace separator left visible. Never ignore
            # punctuation in credentials, emails or other categories.
            sensitive_positions = {i for i in positions if not (
                label == "private_address" and (fixture["text"][i].isspace() or fixture["text"][i] == ","))}
            full = positions <= covered
            content_full = sensitive_positions <= covered
            exact = any(s["start"] == start and s["end"] == start + len(value) for s in spans)
            typed = any(s["label"] == label and positions <= set(range(s["start"], s["end"])) for s in spans)
            count = groups.setdefault(label, {"expected": 0, "fully_hidden": 0, "content_hidden": 0,
                                              "exact": 0, "typed_full": 0})
            count["expected"] += 1
            count["fully_hidden"] += full
            count["content_hidden"] += content_full
            count["exact"] += exact
            count["typed_full"] += typed
            details.append({"id": fixture["id"], "label": label, "value": value,
                            "fully_hidden": full, "partial": bool(positions & covered) and not full,
                            "content_hidden": content_full,
                            "exact": exact, "typed_full": typed})
        if not fixture["expected"] and spans:
            false_positive_cases.append({"id": fixture["id"], "spans": spans})
    total = sum(g["expected"] for g in groups.values())
    hidden = sum(g["fully_hidden"] for g in groups.values())
    content_hidden = sum(g["content_hidden"] for g in groups.values())
    return {"expected_values": total, "fully_hidden": hidden,
            "content_hidden": content_hidden,
            "full_value_recall": hidden / total if total else None,
            "by_category": groups, "values": details,
            "negative_cases": sum(not f["expected"] for f in fixtures),
            "false_positive_cases": false_positive_cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--context", type=int, default=1024)
    parser.add_argument("--max-rss-gib", type=float, default=9)
    parser.add_argument("--quality-only", action="store_true")
    parser.add_argument("--latency-tokens", type=int, nargs="+", default=[64, 256, 1024, 4096])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cpp-library", type=Path)
    parser.add_argument("--cpu-offset", type=int, default=0)
    args = parser.parse_args()
    if args.threads < 1 or args.context < 1 or args.max_rss_gib <= 0 or args.repeats < 1 or min(args.latency_tokens) < 1:
        parser.error("resource bounds must be positive")
    os.nice(10)
    if hasattr(os, "sched_setaffinity"):
        available = sorted(os.sched_getaffinity(0))
        selected = available[args.cpu_offset:args.cpu_offset + args.threads]
        if len(selected) != args.threads:
            parser.error("CPU selection exceeds available CPUs")
        os.sched_setaffinity(0, selected)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(args.threads)
    os.environ["OPF_MOE_TRITON"] = "0"
    os.environ["OPF_TORCH_COMPILE"] = "0"

    def block_network(*_args, **_kwargs):
        raise OSError("Network disabled for offline privacy evaluation")

    socket.socket.connect = block_network
    socket.socket.connect_ex = block_network
    network_isolation = deny_network_syscalls()
    started = time.perf_counter()
    import psutil
    import tiktoken
    if not args.cpp_library:
        import torch
        from opf import OPF
    import_seconds = time.perf_counter() - started
    if not args.cpp_library:
        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
    process = psutil.Process()
    observed_peak = 0
    stop = threading.Event()

    def monitor():
        nonlocal observed_peak
        while not stop.wait(0.1):
            rss = process.memory_info().rss
            observed_peak = max(observed_peak, rss)
            if rss > args.max_rss_gib * 2**30:
                print("Evaluation memory limit exceeded; stopping this process", flush=True)
                os._exit(75)

    threading.Thread(target=monitor, daemon=True).start()
    fixtures = load_json(args.fixtures)
    baseline = load_json(args.baseline)
    load_start = time.perf_counter()
    if args.cpp_library:
        model = CppRedactor(args.cpp_library, args.checkpoint, args.threads, args.context)
        encoding = tiktoken.get_encoding("o200k_base")
        metadata = {"backend": "third-party-ggml-q8", "threshold": 0.0}
    else:
        model = OPF(model=args.checkpoint, device="cpu", context_window_length=args.context)
        runtime, _ = model.get_prediction_components()
        encoding = runtime.encoding
        metadata = {"backend": "official-pytorch-bf16", "torch": torch.__version__,
                    "param_dtype": str(next(runtime.model.parameters()).dtype),
                    "parameter_count": sum(p.numel() for p in runtime.model.parameters())}
    load_seconds = time.perf_counter() - load_start
    result = {"threads": args.threads, "context": args.context, "network_disabled": True,
              "network_isolation": network_isolation,
              **metadata, "import_seconds": import_seconds,
              "load_seconds": load_seconds, "rss_loaded_bytes": process.memory_info().rss,
              "quality": [], "latency": []}
    print(json.dumps({k: v for k, v in result.items() if k not in ("quality", "latency")}), flush=True)
    first_seconds = None
    for fixture in fixtures:
        t = time.perf_counter()
        prediction = model.redact(fixture["text"])
        if not isinstance(prediction, dict):
            prediction = prediction.to_dict()
        seconds = time.perf_counter() - t
        if first_seconds is None:
            first_seconds = seconds
        row = {"id": fixture["id"], "seconds": seconds,
               "tokens": len(encoding.encode(fixture["text"], allowed_special="all")),
               "spans": prediction["detected_spans"], "warning": prediction.get("warning"),
               "source_unchanged": prediction["text"] == fixture["text"]}
        result["quality"].append(row)
        # Save each result so bounded interruption does not discard the evidence.
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"case {fixture['id']}: {seconds:.3f}s, {len(row['spans'])} spans", flush=True)
    result["first_inference_seconds"] = first_seconds
    result["quality_summary"] = score(fixtures, result["quality"])
    result["baseline_summary"] = score(fixtures, baseline)
    baseline_by_id = {r["id"]: r for r in baseline}
    hybrid = [{"id": r["id"], "spans": r["spans"] + baseline_by_id[r["id"]]["spans"]}
              for r in result["quality"]]
    result["hybrid_summary"] = score(fixtures, hybrid)
    configured = [{"id": r["id"], "spans": r.get("configured_spans") or r["spans"]} for r in baseline]
    configured_by_id = {r["id"]: r for r in configured}
    result["configured_baseline_summary"] = score(fixtures, configured)
    result["configured_hybrid_summary"] = score(fixtures, [
        {"id": r["id"], "spans": r["spans"] + configured_by_id[r["id"]]["spans"]}
        for r in result["quality"]])

    if not args.quality_only:
        seed = "The build passed. Update the helper function and keep the existing interface.\n"
        for tokens in args.latency_tokens:
            ids = encoding.encode(seed * (tokens // 10 + 1))[:tokens]
            text = encoding.decode(ids)
            durations = []
            for _ in range(args.repeats):
                t = time.perf_counter()
                model.redact(text)
                durations.append(time.perf_counter() - t)
            row = {"tokens": len(encoding.encode(text)), "seconds": durations,
                   "median_seconds": statistics.median(durations),
                   "maximum_seconds": max(durations), "rss_bytes": process.memory_info().rss}
            result["latency"].append(row)
            print("latency " + json.dumps(row), flush=True)
    result["rss_final_bytes"] = process.memory_info().rss
    result["rss_sampled_peak_bytes"] = observed_peak
    result["rss_os_peak_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["total_seconds"] = time.perf_counter() - started
    stop.set()
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print("complete " + str(args.output), flush=True)


if __name__ == "__main__":
    main()
