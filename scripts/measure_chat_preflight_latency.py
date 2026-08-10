#!/usr/bin/env python3
"""Measure deterministic chat-recovery preflight latency budget inputs.

This non-mutating harness validates nearest-rank p95 calculation and
preflight-before-enqueue ordering. It does not call the deployment or durable
storage, so it cannot demonstrate the live latency budget; a live-dev adapter is
required before reporting cutover latency evidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid


MAX_P95_MS = 250.0


class InMemoryDurableBoundary:
    def __init__(self) -> None:
        self.preflights: dict[str, dict[str, str]] = {}
        self.outbox: dict[str, dict[str, str]] = {}

    def prepare_preflight(self, turn_id: str) -> None:
        preflight_id = str(uuid.uuid5(uuid.UUID(turn_id), "preflight"))
        self.preflights[preflight_id] = {
            "turn_id": turn_id,
            "state": "PREPARED",
        }

    def enqueue_inference(self, turn_id: str) -> None:
        preflight_id = str(uuid.uuid5(uuid.UUID(turn_id), "preflight"))
        if preflight_id not in self.preflights:
            raise AssertionError("inference cannot enqueue before preflight")
        self.outbox[str(uuid.uuid5(uuid.UUID(turn_id), "outbox"))] = {
            "preflight_id": preflight_id,
            "state": "QUEUED",
        }


def nearest_rank_p95(samples: list[float]) -> float:
    if not samples:
        raise AssertionError("samples are required")
    sorted_samples = sorted(samples)
    index = max(0, int(len(sorted_samples) * 0.95 + 0.999999) - 1)
    return sorted_samples[index]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="mock", choices=("mock", "dev"))
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env != "mock":
        raise AssertionError("live latency evidence requires a deployed persistence adapter; use --env mock")
    if args.samples <= 0 or args.warmup < 0 or args.concurrency <= 0:
        raise AssertionError("warmup, samples, and concurrency must be positive")
    if args.concurrency != 1:
        raise AssertionError("mock latency contract runs serially; use --concurrency 1")

    boundary = InMemoryDurableBoundary()
    preflight_ms: list[float] = []
    enqueue_ms: list[float] = []
    total_iterations = args.warmup + args.samples

    for index in range(total_iterations):
        turn_id = str(uuid.uuid5(uuid.UUID("33333333-3333-4333-8333-333333333333"), str(index)))
        started = time.perf_counter()
        boundary.prepare_preflight(turn_id)
        preflight_elapsed = (time.perf_counter() - started) * 1000.0

        enqueue_started = time.perf_counter()
        boundary.enqueue_inference(turn_id)
        enqueue_elapsed = (time.perf_counter() - enqueue_started) * 1000.0

        if index >= args.warmup:
            preflight_ms.append(preflight_elapsed)
            enqueue_ms.append(enqueue_elapsed)

    preflight_p95 = nearest_rank_p95(preflight_ms)
    enqueue_p95 = nearest_rank_p95(enqueue_ms)
    added_p95 = preflight_p95 + enqueue_p95
    assert added_p95 <= MAX_P95_MS

    print(json.dumps({
        "boundary": "in_memory_no_live_epoch_state",
        "env": "mock",
        "evidence_scope": "deterministic_local_contract",
        "samples": args.samples,
        "warmup": args.warmup,
        "execution_concurrency": 1,
        "durability_mode": "in_memory_contract_simulation",
        "runner_region_class": "local_workspace",
        "payload_size_bytes": 0,
        "preflight_p95_ms": round(preflight_p95, 3),
        "enqueue_p95_ms": round(enqueue_p95, 3),
        "added_p95_ms": round(added_p95, 3),
        "mean_added_ms": round(statistics.mean(preflight_ms) + statistics.mean(enqueue_ms), 3),
        "max_budget_ms": MAX_P95_MS,
        "within_budget": None,
        "inference_before_preflight_blocked": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
