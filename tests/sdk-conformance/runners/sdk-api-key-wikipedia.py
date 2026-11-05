#!/usr/bin/env python3
"""Actual SDK wikipedia adapters; developer-only synthetic loopback conformance/CPU lane."""

# contract-test-file: tooling
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import statistics
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "sdk.wikipedia"


def cpu_ticks():
    fields = Path("/proc/self/stat").read_text().rsplit(") ", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def validate_case(c):
    u = urlsplit(c["endpoint"])
    assert (
        u.scheme == "http"
        and u.hostname == "127.0.0.1"
        and u.port
        and not u.username
        and not u.password
        and not u.path
        and not u.query
        and not u.fragment
    )
    assert (
        c["api_key"] == "sk-api-wikipediaOwnerA.localSetupSuffix"
        and c["device_id"] == "synthetic-wikipedia-device"
    )
    assert c.get("iterations", 1) in (1, 1024)


def python_case(c):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError

    v = c["vector"]
    client = OpenMates(
        api_key=None if v["anonymous"] else c["api_key"],
        anonymous=v["anonymous"],
        api_url=c["endpoint"],
        device_id=c["device_id"],
    )

    def invoke():
        options = {"language": v["language"]}
        if v["operation"] == "search":
            return client.wikipedia.search(v["query"], limit=v["limit"], **options)
        if v["operation"] == "summary":
            return client.wikipedia.summary(v["title"], **options)
        if v["operation"] == "learning":
            return client.wikipedia.learning(v["title"], **options)
        assert v["operation"] == "article"
        return client.wikipedia.article(v["title"], **options)

    try:
        start = cpu_ticks()
        wall = time.perf_counter()
        for _ in range(c.get("iterations", 1)):
            value = invoke()
        cpu = cpu_ticks() - start
        elapsed = (time.perf_counter() - wall) * 1000
        result = {"ok": True, "value": value}
        if c.get("iterations", 1) > 1:
            result["performance"] = {
                "iterations": c["iterations"],
                "cpuTicks": cpu,
                "wallMs": elapsed,
            }
        return result
    except OpenMatesConfigError:
        return {"ok": False, "error": "authentication"}
    except OpenMatesApiError as e:
        n = e.status_code
        return {
            "ok": False,
            "error": {401: "authentication", 403: "forbidden", 409: "conflict"}.get(n)
            or (
                "invalid"
                if n in (400, 404, 410, 422)
                else "offline"
                if n == 429 or n >= 500
                else "protocol"
            ),
            "http_status": n,
        }


def command(language, binary):
    if language == "python":
        return [sys.executable, str(Path(__file__)), "--case"]
    if language == "npm":
        return [
            "node",
            "--experimental-strip-types",
            str(ROOT / "tests/sdk-conformance/runners/sdk-api-key-wikipedia.mjs"),
            "--case",
        ]
    b = Path(binary).resolve(strict=True)
    assert b.is_file()
    return [str(b), "--case"]


def adapter(argv, c):
    p = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, _ = p.communicate(
            json.dumps(c).encode(), timeout=120 if c.get("iterations", 1) > 1 else 20
        )
        assert p.returncode == 0 and len(out) <= 1024 * 1024, (
            "bounded wikipedia adapter failed"
        )
        return json.loads(out)
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=2)


def with_peer(suite, vector, language, binary, iterations=1, measurements=None):
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from api_key_wikipedia_peer import WikipediaPeer

    peer = WikipediaPeer(suite, vector, language, iterations)
    server = peer.server()
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        c = {
            "endpoint": f"http://127.0.0.1:{server.server_address[1]}",
            "api_key": suite["api_key"],
            "device_id": suite["device_id"],
            "vector": vector,
            "iterations": iterations,
        }
        observed = adapter(command(language, binary), c)
        if measurements is not None:
            measurements.append(observed)
        assert (
            peer.failure is None
            and peer.requests == vector["expected_request_count"] * iterations
        ), "exact wikipedia wire/request count/no retries"
        if vector["expected_error"]:
            assert (
                observed["ok"] is False
                and observed["error"] == vector["expected_error"]
            )
            if language != "rust" and not vector["anonymous"]:
                assert observed["http_status"] == vector["steps"][-1]["http_status"]
        else:
            assert observed["ok"] is True and observed["value"] == vector["expected"], (
                "opaque JSON output preserved"
            )
        return observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "wikipedia peer cleanup"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="store_true")
    ap.add_argument("--fixture")
    ap.add_argument("--capability")
    ap.add_argument("--language", choices=("rust", "npm", "python"), default="python")
    ap.add_argument("--rust-executable")
    ap.add_argument("--performance", action="store_true")
    ap.add_argument(
        "--performance-operation", choices=("search", "article"), default="search"
    )
    a = ap.parse_args()
    if a.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        c = json.loads(raw)
        validate_case(c)
        print(json.dumps(python_case(c), ensure_ascii=False))
        return
    assert a.capability == CAPABILITY
    raw = Path(a.fixture).resolve(strict=True).read_bytes()
    assert len(raw) <= 1024 * 1024
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    assert 1 <= len(vectors) <= 32 and len({v["id"] for v in vectors}) == len(vectors)
    if a.performance:
        # Identical actual SDK+HTTP+JSON work; peer runs separately and its CPU is excluded.
        # Linux process CPU ticks avoid charging network wait/process startup as CPU work.
        response = {
            "results": [
                {"page_id": i, "title": "Synthetic 界", "snippet": "x" * 240}
                for i in range(128)
            ]
        }
        if a.performance_operation == "search":
            v = {
                "id": "matched-wikipedia-search-cpu",
                "operation": "search",
                "query": "CPU 界 & parity",
                "title": None,
                "language": None,
                "limit": None,
                "anonymous": False,
                "steps": [
                    {
                        "operation": "search",
                        "http_status": 200,
                        "response": response,
                        "expected_title": None,
                    }
                ],
                "expected": response,
                "expected_request_count": 1,
                "expected_error": None,
            }
        else:
            summary = {
                "title": "Canonical CPU",
                "extract": "x" * 32768,
                "opaque": [None, False, 1],
            }
            guide = {
                "canonical_title": "Canonical CPU",
                "language": "en",
                "source_url": "https://example.invalid/synthetic",
                "questions": ["Synthetic Q?"] * 32,
                "related_articles": [
                    {
                        "title": "Related",
                        "canonical_title": "Related",
                        "language": "en",
                        "description": "Synthetic",
                    }
                ]
                * 32,
                "expires_in_seconds": 60,
            }
            v = {
                "id": "matched-wikipedia-article-cpu",
                "operation": "article",
                "query": None,
                "title": "Input CPU",
                "language": None,
                "limit": None,
                "anonymous": False,
                "steps": [
                    {
                        "operation": "summary",
                        "http_status": 200,
                        "response": summary,
                        "expected_title": "Input CPU",
                    },
                    {
                        "operation": "learning",
                        "http_status": 200,
                        "response": guide,
                        "expected_title": "Canonical CPU",
                    },
                ],
                "expected": {
                    **summary,
                    "questions": guide["questions"],
                    "related_articles": guide["related_articles"],
                    "suggestions_unavailable": False,
                },
                "expected_request_count": 2,
                "expected_error": None,
            }
        observations = {"rust": [], "npm": []}
        report = {
            "capability": CAPABILITY,
            "operation": a.performance_operation,
            "status": "failed",
            "scope": "matched actual direct SDK GET+JSON response work over synthetic loopback; own-process CPU excludes peer CPU, startup and waiting; wall includes local HTTP wait, not deployed network proof",
            "clockTicksPerSecond": os.sysconf("SC_CLK_TCK"),
            "samples": observations,
            "releaseEligible": False,
        }
        try:
            for pair in range(5):
                for lang in ("rust", "npm") if pair % 2 == 0 else ("npm", "rust"):
                    report["failureStage"] = "adapter_or_protocol"
                    report["failedSample"] = {"pair": pair, "language": lang}
                    observed = with_peer(
                        suite, v, lang, a.rust_executable, 1024, observations[lang]
                    )
                    report["failureStage"] = "insufficient_cpu_resolution"
                    m = observed["performance"]
                    assert m["iterations"] == 1024 and m["cpuTicks"] >= 20, (
                        "insufficient CPU resolution; do not claim parity"
                    )
            rust_cpu = statistics.median(
                x["performance"]["cpuTicks"] for x in observations["rust"]
            )
            ts_cpu = statistics.median(
                x["performance"]["cpuTicks"] for x in observations["npm"]
            )
            rust_wall = statistics.median(
                x["performance"]["wallMs"] for x in observations["rust"]
            )
            ts_wall = statistics.median(
                x["performance"]["wallMs"] for x in observations["npm"]
            )
            report.update(
                {
                    "rustAtLeastAsFastCpu": rust_cpu <= ts_cpu,
                    "rustAtLeastAsFastLoopbackWall": rust_wall <= ts_wall,
                    "failureStage": "rust_slower_than_typescript",
                }
            )
            assert rust_cpu <= ts_cpu and rust_wall <= ts_wall, (
                "Rust SDK wikipedia performance below TypeScript"
            )
            report["status"] = "passed"
            report.pop("failureStage")
            report.pop("failedSample")
        finally:
            # Emit even the current failed/raw sample and all earlier samples before refusal.
            print(json.dumps(report))
        return
    results = []
    for v in vectors:
        with_peer(suite, v, a.language, a.rust_executable)
        results.append({"id": v["id"], "status": "passed"})
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": a.language,
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("wikipedia direct SDK conformance failed", file=sys.stderr)
        sys.exit(1)
