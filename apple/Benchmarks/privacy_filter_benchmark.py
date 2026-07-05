#!/usr/bin/env python3
"""Benchmark OpenAI Privacy Filter on Mac hardware.

This Mac-only harness loads the open-weight `openai/privacy-filter` model
locally, evaluates it on synthetic OpenMates-style chat messages, compares it
with a deliberately simple regex baseline, and emits privacy-safe aggregate
accuracy plus performance metrics. It is intended for Apple Remote runs on real
Apple Silicon before product integration decisions are made.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MODEL = "openai/privacy-filter"
DEFAULT_FIXTURES = Path(__file__).with_name("privacy_filter_fixtures.json")
MODEL_LABELS = {
    "private_person",
    "private_address",
    "private_email",
    "private_phone",
    "private_url",
    "private_date",
    "account_number",
    "secret",
}


@dataclass(frozen=True)
class ExpectedSpan:
    label: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Detection:
    label: str
    start: int
    end: int
    score: float | None
    source: str

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


@dataclass(frozen=True)
class SystemSample:
    timestamp: float
    process_rss_mb: float | None
    process_cpu_percent: float | None
    system_memory_used_mb: float | None
    system_memory_percent: float | None


class MetricSampler:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[SystemSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: Any | None = None
        self._psutil: Any | None = None

    def __enter__(self) -> "MetricSampler":
        try:
            import psutil  # type: ignore

            self._psutil = psutil
            self._process = psutil.Process(os.getpid())
            self._process.cpu_percent(interval=None)
        except Exception:
            self._psutil = None
            self._process = None
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds * 2)
        self.sample_once()

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.interval_seconds)

    def sample_once(self) -> None:
        process_rss_mb = current_rss_mb()
        process_cpu_percent = None
        system_memory_used_mb = None
        system_memory_percent = None
        if self._psutil is not None and self._process is not None:
            try:
                process_rss_mb = self._process.memory_info().rss / 1024 / 1024
                process_cpu_percent = self._process.cpu_percent(interval=None)
                virtual_memory = self._psutil.virtual_memory()
                system_memory_used_mb = virtual_memory.used / 1024 / 1024
                system_memory_percent = virtual_memory.percent
            except Exception:
                pass
        self.samples.append(
            SystemSample(
                timestamp=time.time(),
                process_rss_mb=process_rss_mb,
                process_cpu_percent=process_cpu_percent,
                system_memory_used_mb=system_memory_used_mb,
                system_memory_percent=system_memory_percent,
            )
        )

    def summary(self) -> dict[str, Any]:
        rss_values = [sample.process_rss_mb for sample in self.samples if sample.process_rss_mb is not None]
        cpu_values = [sample.process_cpu_percent for sample in self.samples if sample.process_cpu_percent is not None]
        system_memory_values = [sample.system_memory_percent for sample in self.samples if sample.system_memory_percent is not None]
        return {
            "sample_count": len(self.samples),
            "process_rss_mb_peak": round(max(rss_values), 2) if rss_values else None,
            "process_rss_mb_mean": round(statistics.fmean(rss_values), 2) if rss_values else None,
            "process_cpu_percent_peak": round(max(cpu_values), 2) if cpu_values else None,
            "process_cpu_percent_mean": round(statistics.fmean(cpu_values), 2) if cpu_values else None,
            "system_memory_percent_peak": round(max(system_memory_values), 2) if system_memory_values else None,
            "system_memory_percent_mean": round(statistics.fmean(system_memory_values), 2) if system_memory_values else None,
            "gpu_or_ane_note": "Not available from this in-process harness; use Instruments or powermetrics externally for GPU/ANE counters.",
        }


def current_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return usage / 1024 / 1024
    return usage / 1024


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        fixtures = json.load(handle)
    if not isinstance(fixtures, list):
        raise ValueError(f"Fixture file must contain a list: {path}")
    for fixture in fixtures:
        if not isinstance(fixture.get("text"), str) or not isinstance(fixture.get("expected"), list):
            raise ValueError(f"Invalid fixture shape for {fixture.get('id', '<unknown>')}")
    return fixtures


def expected_spans(fixture: dict[str, Any]) -> list[ExpectedSpan]:
    text = fixture["text"]
    spans: list[ExpectedSpan] = []
    for expected in fixture["expected"]:
        label = normalize_label(expected["label"])
        expected_text = expected["text"]
        start = text.find(expected_text)
        if start < 0:
            raise ValueError(f"Expected text not found in fixture {fixture['id']}: {expected_text}")
        spans.append(ExpectedSpan(label=label, text=expected_text, start=start, end=start + len(expected_text)))
    return spans


def normalize_label(label: str) -> str:
    normalized = label.strip().lower()
    for prefix in ("b-", "i-", "e-", "s-"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    aliases = {
        "email": "private_email",
        "phone": "private_phone",
        "url": "private_url",
        "date": "private_date",
        "person": "private_person",
        "address": "private_address",
        "account": "account_number",
        "credential": "secret",
    }
    return aliases.get(normalized, normalized)


def spans_overlap(first_start: int, first_end: int, second_start: int, second_end: int) -> bool:
    return max(first_start, second_start) < min(first_end, second_end)


def label_compatible(detected: str, expected: str) -> bool:
    if detected == expected:
        return True
    if expected == "secret" and detected == "account_number":
        return True
    return False


def evaluate_detections(expected: list[ExpectedSpan], detected: list[Detection]) -> dict[str, Any]:
    matched_detection_indexes: set[int] = set()
    missed: list[ExpectedSpan] = []
    label_mismatches: list[dict[str, str]] = []

    for span in expected:
        overlapping = [
            (index, detection)
            for index, detection in enumerate(detected)
            if spans_overlap(span.start, span.end, detection.start, detection.end)
        ]
        compatible = [
            (index, detection)
            for index, detection in overlapping
            if label_compatible(detection.label, span.label)
        ]
        if compatible:
            matched_detection_indexes.add(compatible[0][0])
            continue
        if overlapping:
            label_mismatches.append({"expected": span.label, "detected": overlapping[0][1].label})
            matched_detection_indexes.add(overlapping[0][0])
            continue
        missed.append(span)

    false_positives = [
        detection
        for index, detection in enumerate(detected)
        if index not in matched_detection_indexes
    ]
    return {
        "expected_count": len(expected),
        "detected_count": len(detected),
        "hit_count": len(expected) - len(missed) - len(label_mismatches),
        "miss_count": len(missed),
        "label_mismatch_count": len(label_mismatches),
        "false_positive_count": len(false_positives),
        "missed_labels": sorted(span.label for span in missed),
        "false_positive_labels": sorted(detection.label for detection in false_positives),
        "label_mismatches": label_mismatches,
    }


def aggregate_evaluations(evaluations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(evaluations)
    expected_total = sum(item["expected_count"] for item in items)
    hit_total = sum(item["hit_count"] for item in items)
    false_positive_total = sum(item["false_positive_count"] for item in items)
    detected_total = sum(item["detected_count"] for item in items)
    miss_total = sum(item["miss_count"] for item in items)
    mismatch_total = sum(item["label_mismatch_count"] for item in items)
    precision_denominator = hit_total + false_positive_total + mismatch_total
    recall = hit_total / expected_total if expected_total else 1.0
    precision = hit_total / precision_denominator if precision_denominator else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "fixtures": len(items),
        "expected_total": expected_total,
        "detected_total": detected_total,
        "hit_total": hit_total,
        "miss_total": miss_total,
        "label_mismatch_total": mismatch_total,
        "false_positive_total": false_positive_total,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


class RegexBaseline:
    def __init__(self) -> None:
        self.patterns: list[tuple[str, re.Pattern[str]]] = [
            ("private_email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
            ("private_phone", re.compile(r"(?:\+|00)?\d[\d\s()./-]{7,}\d")),
            ("private_url", re.compile(r"https?://[^\s]+", re.IGNORECASE)),
            ("account_number", re.compile(r"\b(?:\d[ -]?){12,19}\b|\b[A-Z]{2}\d{2}(?:[\s]?[A-Z0-9]{4}){3,7}\b")),
            ("private_date", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})\b", re.IGNORECASE)),
            ("secret", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|password\s*=\s*[^\s.]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)")),
        ]

    def __call__(self, text: str) -> list[Detection]:
        detections: list[Detection] = []
        occupied: list[tuple[int, int]] = []
        for label, pattern in self.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(spans_overlap(start, end, existing_start, existing_end) for existing_start, existing_end in occupied):
                    continue
                occupied.append((start, end))
                detections.append(Detection(label=label, start=start, end=end, score=None, source="regex"))
        return sorted(detections, key=lambda detection: detection.start)


def select_device(requested: str) -> tuple[str, str | int]:
    if requested == "cpu":
        return "cpu", -1
    try:
        import torch  # type: ignore
    except Exception:
        return "cpu", -1
    if requested in {"auto", "mps"} and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", "mps"
    if requested == "mps":
        raise RuntimeError("MPS was requested, but torch.backends.mps is not available")
    return "cpu", -1


def dtype_value(dtype_name: str) -> Any | None:
    if dtype_name == "default":
        return None
    import torch  # type: ignore

    values = {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }
    return values[dtype_name]


def load_privacy_filter(model_name: str, device_request: str, dtype_name: str) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    try:
        import torch  # type: ignore
        from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing benchmark dependencies. Install on the Mac with: "
            "python3 -m pip install 'transformers>=4.52' 'torch>=2.3' 'accelerate>=0.30' psutil"
        ) from exc

    resolved_device_name, pipeline_device = select_device(device_request)
    model_kwargs: dict[str, Any] = {}
    selected_dtype = dtype_value(dtype_name)
    if selected_dtype is not None:
        model_kwargs["torch_dtype"] = selected_dtype

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name, **model_kwargs)
    if resolved_device_name == "mps":
        model = model.to("mps")
    classifier = pipeline(
        task="token-classification",
        model=model,
        tokenizer=tokenizer,
        device=pipeline_device,
        aggregation_strategy="simple",
    )
    loaded = time.perf_counter()
    metadata = {
        "model": model_name,
        "device": resolved_device_name,
        "requested_device": device_request,
        "dtype": dtype_name,
        "torch_version": torch.__version__,
        "load_time_ms": round((loaded - started) * 1000, 2),
        "rss_after_load_mb": round(current_rss_mb(), 2),
    }
    return classifier, metadata


def model_detections(classifier: Any, text: str) -> list[Detection]:
    raw_outputs = classifier(text)
    detections: list[Detection] = []
    for output in raw_outputs:
        raw_label = output.get("entity_group") or output.get("entity") or ""
        label = normalize_label(str(raw_label))
        if label not in MODEL_LABELS:
            continue
        start = output.get("start")
        end = output.get("end")
        if start is None or end is None:
            word = str(output.get("word", "")).strip()
            if not word:
                continue
            found = text.find(word)
            if found < 0:
                continue
            start = found
            end = found + len(word)
        detections.append(
            Detection(
                label=label,
                start=int(start),
                end=int(end),
                score=float(output["score"]) if output.get("score") is not None else None,
                source="openai/privacy-filter",
            )
        )
    return sorted(detections, key=lambda detection: detection.start)


def timed_inference(detector: Any, text: str, repeat_count: int) -> tuple[list[Detection], list[float]]:
    durations_ms: list[float] = []
    detections: list[Detection] = []
    for _ in range(repeat_count):
        started = time.perf_counter()
        detections = detector(text)
        durations_ms.append((time.perf_counter() - started) * 1000)
    return detections, durations_ms


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * percent)))
    return sorted_values[index]


def summarize_latencies(values: list[float]) -> dict[str, float | None]:
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 2) if values else None,
        "median_ms": round(statistics.median(values), 2) if values else None,
        "p95_ms": round(percentile(values, 0.95), 2) if values else None,
        "max_ms": round(max(values), 2) if values else None,
    }


def sanitized_detection_summary(detections: list[Detection]) -> list[dict[str, Any]]:
    return [
        {
            "label": detection.label,
            "start": detection.start,
            "end": detection.end,
            "length": detection.length,
            "score": round(detection.score, 4) if detection.score is not None else None,
        }
        for detection in detections
    ]


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    fixtures = load_fixtures(args.fixtures)
    regex = RegexBaseline()
    classifier, model_metadata = load_privacy_filter(args.model, args.device, args.dtype)

    model_case_results: list[dict[str, Any]] = []
    regex_case_results: list[dict[str, Any]] = []
    all_model_latencies: list[float] = []
    all_regex_latencies: list[float] = []

    with MetricSampler(args.sample_interval) as sampler:
        for fixture in fixtures:
            spans = expected_spans(fixture)
            text = fixture["text"]
            model_result, model_latencies = timed_inference(lambda value: model_detections(classifier, value), text, args.repeat)
            regex_result, regex_latencies = timed_inference(regex, text, args.repeat)
            all_model_latencies.extend(model_latencies)
            all_regex_latencies.extend(regex_latencies)

            model_evaluation = evaluate_detections(spans, model_result)
            regex_evaluation = evaluate_detections(spans, regex_result)
            model_case_results.append({
                "id": fixture["id"],
                "description": fixture.get("description"),
                "char_count": len(text),
                "expected_labels": sorted(span.label for span in spans),
                "evaluation": model_evaluation,
                "latency": summarize_latencies(model_latencies),
                "detections": sanitized_detection_summary(model_result),
            })
            regex_case_results.append({
                "id": fixture["id"],
                "evaluation": regex_evaluation,
                "latency": summarize_latencies(regex_latencies),
                "detections": sanitized_detection_summary(regex_result),
            })
        metrics = sampler.summary()

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": host_metadata(),
        "model": model_metadata,
        "run_config": {
            "fixtures": str(args.fixtures),
            "repeat": args.repeat,
            "sample_interval_seconds": args.sample_interval,
        },
        "accuracy": {
            "openai_privacy_filter": aggregate_evaluations(item["evaluation"] for item in model_case_results),
            "regex_baseline": aggregate_evaluations(item["evaluation"] for item in regex_case_results),
        },
        "performance": {
            "openai_privacy_filter_latency": summarize_latencies(all_model_latencies),
            "regex_baseline_latency": summarize_latencies(all_regex_latencies),
            "system_metrics": metrics,
        },
        "cases": {
            "openai_privacy_filter": model_case_results,
            "regex_baseline": regex_case_results,
        },
    }


def host_metadata() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }


def print_summary(report: dict[str, Any]) -> None:
    model_accuracy = report["accuracy"]["openai_privacy_filter"]
    regex_accuracy = report["accuracy"]["regex_baseline"]
    model_latency = report["performance"]["openai_privacy_filter_latency"]
    system_metrics = report["performance"]["system_metrics"]
    print("OpenAI Privacy Filter Mac benchmark")
    print(f"model_device={report['model']['device']} dtype={report['model']['dtype']} load_ms={report['model']['load_time_ms']}")
    print(
        "privacy_filter "
        f"precision={model_accuracy['precision']} recall={model_accuracy['recall']} f1={model_accuracy['f1']} "
        f"misses={model_accuracy['miss_total']} false_positives={model_accuracy['false_positive_total']}"
    )
    print(
        "regex_baseline "
        f"precision={regex_accuracy['precision']} recall={regex_accuracy['recall']} f1={regex_accuracy['f1']} "
        f"misses={regex_accuracy['miss_total']} false_positives={regex_accuracy['false_positive_total']}"
    )
    print(
        "performance "
        f"mean_ms={model_latency['mean_ms']} median_ms={model_latency['median_ms']} "
        f"p95_ms={model_latency['p95_ms']} max_ms={model_latency['max_ms']} "
        f"rss_peak_mb={system_metrics['process_rss_mb_peak']} cpu_peak_percent={system_metrics['process_cpu_percent_peak']}"
    )
    print("case_results")
    for item in report["cases"]["openai_privacy_filter"]:
        evaluation = item["evaluation"]
        print(
            f"- {item['id']}: hits={evaluation['hit_count']}/{evaluation['expected_count']} "
            f"misses={evaluation['miss_count']} mismatches={evaluation['label_mismatch_count']} "
            f"false_positives={evaluation['false_positive_count']} latency_mean_ms={item['latency']['mean_ms']}"
        )


def write_report(report: dict[str, Any], output: Path | None) -> Path | None:
    if output is None:
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenAI Privacy Filter against OpenMates-style PII fixtures on Mac hardware.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    parser.add_argument("--dtype", choices=["default", "float32", "float16", "bfloat16"], default="default")
    parser.add_argument("--repeat", type=int, default=3, help="Inference repeats per fixture after model load.")
    parser.add_argument("--sample-interval", type=float, default=0.2)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path. Use /tmp for local benchmark artifacts.")
    parser.add_argument("--install-command", action="store_true", help="Print the dependency install command and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.install_command:
        print("python3 -m pip install 'transformers>=4.52' 'torch>=2.3' 'accelerate>=0.30' psutil")
        return 0
    if platform.system() != "Darwin":
        print("warning=benchmark_is_intended_for_mac_hardware", file=sys.stderr)
    if args.repeat < 1:
        raise ValueError("--repeat must be >= 1")
    started = time.perf_counter()
    report = run_benchmark(args)
    report["wall_time_ms"] = round((time.perf_counter() - started) * 1000, 2)
    written = write_report(report, args.output)
    print_summary(report)
    if written is not None:
        print(f"json_report={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
