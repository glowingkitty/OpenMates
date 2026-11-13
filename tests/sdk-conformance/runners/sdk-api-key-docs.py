#!/usr/bin/env python3
"""Actual SDK docs adapters; developer-only synthetic loopback conformance/CPU lane."""

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
CAPABILITY = "sdk.docs"
# BEGIN CLOSED DOCS DIAGNOSTIC
DOCS_STAGES = (
    "arguments",
    "fixture_read",
    "fixture_contract",
    "vector_admission",
    "peer_start",
    "case_input",
    "adapter_launch",
    "adapter_process",
    "adapter_decode",
    "peer_assert",
    "response_assert",
    "peer_cleanup",
    "record_result",
    "result_summary",
    "emit_result",
    "performance",
    "unclassified",
)
DOCS_VECTOR_IDS = (
    "list-full-tree-extension-fields",
    "search-unicode-query",
    "search-empty-query",
    "search-whitespace-query",
    "search-long-server-owned-query",
    "show-slash-space",
    "show-reserved-unicode",
    "download-slash-space",
    "download-reserved-unicode",
    "http-400",
    "http-401",
    "http-403",
    "http-404",
    "http-409",
    "http-422",
    "http-429",
    "http-500",
    "opaque-success-array",
    "opaque-success-null",
    "anonymous-list",
    "anonymous-search",
    "anonymous-show",
    "anonymous-download",
    "slug-empty-refused-locally",
    "slug-traversal-refused-locally",
    "slug-absolute-refused-locally",
    "slug-trailing-slash-refused-locally",
    "slug-empty-segment-refused-locally",
    "slug-backslash-refused-locally",
    "slug-colon-refused-locally",
    "slug-control-refused-locally",
    "slug-oversize-utf8-bytes-refused-locally",
)
DOCS_ERRORS = (
    "assertion",
    "timeout",
    "module_not_found",
    "json_decode",
    "os_error",
    "unclassified",
)
DOCS_CHILD_STAGES = (
    "sdk_import",
    "input_read",
    "input_decode",
    "input_admission",
    "client_constructor",
    "invoke",
    "error_mapping",
    "emit_result",
    "unclassified",
    "none",
)
DOCS_CHILD_ERRORS = (
    "assertion",
    "module_not_found",
    "module_export_missing",
    "unsupported_ts_syntax",
    "syntax",
    "type",
    "reference",
    "sdk_config",
    "sdk_api",
    "unclassified",
    "none",
)
DOCS_SUITE_STAGES = (
    "arguments",
    "fixture_read",
    "fixture_contract",
    "vector_admission",
    "peer_start",
    "case_input",
    "adapter_launch",
    "result_summary",
    "emit_result",
    "performance",
    "unclassified",
)
DOCS_STAGE = "arguments"
DOCS_VECTOR = "none"
DOCS_CHILD = ("none", "none")


def docs_error(error):
    if isinstance(error, AssertionError):
        return "assertion"
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(error, ModuleNotFoundError):
        return "module_not_found"
    if isinstance(error, json.JSONDecodeError):
        return "json_decode"
    if isinstance(error, OSError):
        return "os_error"
    return "unclassified"


def docs_child(stderr):
    # Unrelated stderr stays private. Only ONE exact source-owned finite line is read.
    if not isinstance(stderr, bytes) or len(stderr) > 65536:
        return ("none", "none")
    found = []
    for stage in DOCS_CHILD_STAGES[:-1]:
        for error in DOCS_CHILD_ERRORS[:-1]:
            line = (
                "npm docs diagnostic: stage=" + stage + ";error=" + error + "\n"
            ).encode()
            occurrences = stderr.splitlines(keepends=True).count(line)
            if occurrences:
                found.extend([(stage, error)] * occurrences)
    return found[0] if len(found) == 1 else ("none", "none")


def docs_line(stage, vector, error, child):
    stage = stage if type(stage) is str and stage in DOCS_STAGES else "unclassified"
    vector = (
        vector
        if stage not in DOCS_SUITE_STAGES
        and type(vector) is str
        and vector in DOCS_VECTOR_IDS
        else "none"
    )
    error = error if type(error) is str and error in DOCS_ERRORS else "unclassified"
    child = (
        child
        if type(child) is tuple
        and len(child) == 2
        and child[0] in DOCS_CHILD_STAGES
        and child[1] in DOCS_CHILD_ERRORS
        else ("none", "none")
    )
    if child[0] in ("sdk_import", "input_read", "input_decode", "input_admission") or (
        stage == "adapter_process" and child[0] == "none"
    ):
        vector = "none"
    return f"docs diagnostic: stage={stage};vector={vector};error={error};childStage={child[0]};childError={child[1]}\n"


def decode_docs_digest(count, digest):
    if (
        type(count) is not int
        or count < 0
        or type(digest) is not str
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("closed_digest_identity")
    generic = b"docs direct SDK conformance failed\n"
    if count == len(generic) and hashlib.sha256(generic).hexdigest() == digest:
        return {
            "status": "generic-only",
            "stage": "unclassified",
            "vector": "none",
            "error": "unclassified",
        }
    for stage in DOCS_STAGES:
        vectors = (
            ("none",) if stage in DOCS_SUITE_STAGES else ("none", *DOCS_VECTOR_IDS)
        )
        for vector in vectors:
            for error in DOCS_ERRORS:
                for child_stage in DOCS_CHILD_STAGES:
                    for child_error in DOCS_CHILD_ERRORS:
                        line = docs_line(
                            stage, vector, error, (child_stage, child_error)
                        )
                        raw = generic + line.encode()
                        if (
                            len(raw) == count
                            and hashlib.sha256(raw).hexdigest() == digest
                        ):
                            fields = dict(
                                field.split("=", 1)
                                for field in line.strip()
                                .removeprefix("docs diagnostic: ")
                                .split(";")
                            )
                            return {
                                "status": "matched",
                                **fields,
                                "attribution": "suite-only"
                                if fields["vector"] == "none"
                                else "admitted-vector-stage",
                            }
    return {"status": "unmatched"}


# END CLOSED DOCS DIAGNOSTIC
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
        c["api_key"] == "sk-api-docsOwnerA.localSetupSuffix"
        and c["device_id"] == "synthetic-docs-device"
    )
    assert c.get("iterations", 1) in (1, 1024)


def python_case(c):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import (
        OpenMates,
        OpenMatesApiError,
        OpenMatesConfigError,
        OpenMatesInvalidInputError,
    )

    v = c["vector"]
    client = OpenMates(
        api_key=None if v["anonymous"] else c["api_key"],
        anonymous=v["anonymous"],
        api_url=c["endpoint"],
        device_id=c["device_id"],
    )

    def invoke():
        if v["operation"] == "list":
            return client.docs.list()
        if v["operation"] == "search":
            return client.docs.search(v["query"])
        if v["operation"] == "show":
            return client.docs.show(v["slug"])
        assert v["operation"] == "download"
        return client.docs.download(v["slug"])

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
    except OpenMatesInvalidInputError:
        # Shared Rust slug policy refusal before transport (Rust Error::Invalid).
        return {"ok": False, "error": "invalid"}
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
            str(ROOT / "tests/sdk-conformance/runners/sdk-api-key-docs.mjs"),
            "--case",
        ]
    b = Path(binary).resolve(strict=True)
    assert b.is_file()
    return [str(b), "--case"]


def adapter(argv, c):
    global DOCS_STAGE, DOCS_CHILD
    DOCS_STAGE = "adapter_launch"
    DOCS_CHILD = ("none", "none")
    p = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        DOCS_STAGE = "adapter_process"
        out, private_stderr = p.communicate(
            json.dumps(c).encode(), timeout=120 if c.get("iterations", 1) > 1 else 20
        )
        DOCS_CHILD = docs_child(private_stderr)
        assert p.returncode == 0 and len(out) <= 1024 * 1024, (
            "bounded docs adapter failed"
        )
        DOCS_STAGE = "adapter_decode"
        return json.loads(out)
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=2)


def with_peer(suite, vector, language, binary, iterations=1, measurements=None):
    global DOCS_STAGE
    DOCS_STAGE = "peer_start"
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from api_key_docs_peer import DocsPeer

    peer = DocsPeer(suite, vector, language, iterations)
    server = peer.server()
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        DOCS_STAGE = "case_input"
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
        DOCS_STAGE = "peer_assert"
        assert (
            peer.failure is None
            and peer.requests == vector["expected_request_count"] * iterations
        ), "exact docs wire/request count/no retries"
        DOCS_STAGE = "response_assert"
        if vector["expected_error"]:
            assert (
                observed["ok"] is False
                and observed["error"] == vector["expected_error"]
            )
            # Anonymous and local slug refusals never reach transport.
            if language != "rust" and vector["expected_request_count"]:
                assert observed["http_status"] == vector["http_status"]
        else:
            assert observed["ok"] is True and observed["value"] == vector["response"], (
                "opaque JSON output preserved"
            )
        return observed
    finally:
        previous_stage = DOCS_STAGE
        DOCS_STAGE = "peer_cleanup"
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "docs peer cleanup"
        DOCS_STAGE = previous_stage


def main():
    global DOCS_STAGE, DOCS_VECTOR, DOCS_CHILD
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="store_true")
    ap.add_argument("--fixture")
    ap.add_argument("--capability")
    ap.add_argument("--language", choices=("rust", "npm", "python"), default="python")
    ap.add_argument("--rust-executable")
    ap.add_argument("--performance", action="store_true")
    a = ap.parse_args()
    if a.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        c = json.loads(raw)
        validate_case(c)
        print(json.dumps(python_case(c), ensure_ascii=False))
        return
    assert a.capability == CAPABILITY
    DOCS_STAGE = "fixture_read"
    raw = Path(a.fixture).resolve(strict=True).read_bytes()
    assert len(raw) <= 1024 * 1024
    DOCS_STAGE = "fixture_contract"
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    assert 1 <= len(vectors) <= 32 and len({v["id"] for v in vectors}) == len(vectors)
    if a.performance:
        DOCS_STAGE = "performance"
        DOCS_VECTOR = "none"
        # Identical actual SDK+HTTP+JSON work; peer runs separately and its CPU is excluded.
        # Linux process CPU ticks avoid charging network wait/process startup as CPU work.
        v = {
            "id": "matched-docs-json-cpu",
            "operation": "search",
            "query": "CPU 界 & parity",
            "slug": None,
            "anonymous": False,
            "http_status": 200,
            "response": {
                "results": [
                    {
                        "slug": f"guide/{i}",
                        "title": "Synthetic 界",
                        "snippet": "x" * 240,
                    }
                    for i in range(128)
                ]
            },
            "expected_request_count": 1,
            "expected_error": None,
        }
        observations = {"rust": [], "npm": []}
        report = {
            "capability": CAPABILITY,
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
                "Rust SDK docs performance below TypeScript"
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
        DOCS_STAGE = "vector_admission"
        DOCS_VECTOR = (
            v.get("id")
            if type(v) is dict and v.get("id") in DOCS_VECTOR_IDS
            else "none"
        )
        DOCS_CHILD = ("none", "none")
        with_peer(suite, v, a.language, a.rust_executable)
        DOCS_STAGE = "record_result"
        results.append({"id": v["id"], "status": "passed"})
        DOCS_VECTOR = "none"
    DOCS_STAGE = "emit_result"
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
    except Exception as error:
        print("docs direct SDK conformance failed", file=sys.stderr)
        sys.stderr.write(
            docs_line(DOCS_STAGE, DOCS_VECTOR, docs_error(error), DOCS_CHILD)
        )
        sys.exit(1)
