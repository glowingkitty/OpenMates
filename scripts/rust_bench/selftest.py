"""Meter smoke checks against trivial commands (no CLI, no network, no account).

Proves that wall time, CPU of child AND orphaned grandchild processes, and peak
memory are captured by the selected meter backend.
"""

from __future__ import annotations

import os
import sys

from .meter import Meter

ALLOC_MIB = 96
BUSY_SECONDS = 0.3

_ALLOC = (
    "import sys,time\n"
    f"b=bytearray({ALLOC_MIB}*1024*1024)\n"
    "for i in range(0,len(b),4096): b[i]=1\n"
    "time.sleep(0.05)\n"
)
_BUSY = (
    "import time\n"
    f"end=time.process_time()+{BUSY_SECONDS}\n"
    "while time.process_time()<end: pass\n"
)


def cases(python: str = sys.executable) -> list[dict]:
    return [
        {"name": "sleep-0.1", "argv": ["sleep", "0.1"],
         # Upper memory bound proves the harness's own (Python) pages are not
         # inherited into the measured high-water mark.
         "expect": {"wallMs": (95, 1000), "cpuMs": (0, 50), "peakMemKiB": (1, 8192)}},
        {"name": "alloc-child", "argv": [python, "-c", _ALLOC],
         "expect": {"peakMemKiB": (ALLOC_MIB * 1024, None), "maxRssKiB": (ALLOC_MIB * 1024, None)}},
        # Grandchild waited for by its parent shell: CPU and RSS fold into the shell's rusage.
        {"name": "busy-grandchild", "argv": ["sh", "-c", f'"{python}" -c "$1"; "{python}" -c "$2"', "sh",
                                              _BUSY, _ALLOC],
         "expect": {"cpuMs": (BUSY_SECONDS * 1000 * 0.9, None), "peakMemKiB": (ALLOC_MIB * 1024, None)}},
        # Orphan: the main shell exits immediately; the detached grandchild is
        # re-parented to the subreaper harness and must still be accounted.
        {"name": "orphan-grandchild", "argv": ["sh", "-c", f'("{python}" -c "$1" &) ; exit 0', "sh",
                                                _BUSY + _ALLOC],
         "expect": {"wallMs": (0, 250), "cpuMs": (BUSY_SECONDS * 1000 * 0.9, None),
                    "peakMemKiB": (ALLOC_MIB * 1024, None), "processesReaped": (2, None)}},
    ]


def check(result: dict, expect: dict) -> list[str]:
    problems = []
    for key, (low, high) in expect.items():
        value = result.get(key)
        if value is None or value < low or (high is not None and value > high):
            problems.append(f"{key}={value} not in [{low}, {high if high is not None else 'inf'}]")
    return problems


def run_selftest(meter: Meter) -> dict:
    results = []
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for case in cases():
        metrics = meter.run(case["argv"], env, timeout=30)
        problems = check(metrics, case["expect"]) + ([] if metrics["exitCode"] == 0 else ["nonzero exit"])
        results.append({"name": case["name"], "ok": not problems, "problems": problems, "metrics": metrics})
    return {"meter": meter.describe(), "ok": all(r["ok"] for r in results), "cases": results}
