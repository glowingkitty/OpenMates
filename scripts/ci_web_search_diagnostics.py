"""Bounded metadata-only diagnostics for two isolated web-search cases.

This module neither changes a test verdict nor retains raw service logs. Only
the trusted runner starts its literal read-only Compose follower.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SPEC = "skill-web-search.spec.ts"
CASES = {
    "Phase 5: Zero-result query does not show error banner": "web_search_zero_results",
    "Phase 4: Web chat triggers web search with embed": "web_search_web",
}
ATTACHMENT = "web-search-correlation"
MAX_LINE = 64 * 1024
MAX_EVENTS = 2048
MAX_CONTEXTS = 64
MAX_MEMORY = 1024 * 1024
MAX_OUTPUT = 256 * 1024
MAX_STORE = MAX_MEMORY - 2 * MAX_OUTPUT - MAX_LINE - 256 * 1024
MAX_SECONDS = 1210
MAX_BROWSER = 16 * 1024
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
UUID_RE = re.compile(UUID + r"\Z")
MESSAGE_ID = rf"(?:[0-9a-f]{{10}}-)?{UUID}"
API_LOGGER = "backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler"
ASK_LOGGER = "backend.apps.ai.tasks.ask_skill_task"
CELERY_LOGGER = "backend.core.api.app.tasks.celery_config"
OUTGOING = {"chat_turn_preflight", "chat_turn_admit", "chat_message_added"}
STAGES = {
    "Received apps.ai.tasks.skill_ask task": "task_entry",
    "Starting preprocessing step": "preprocessing",
    "Starting main processing step": "main",
    "Starting post-processing step": "postprocessing",
    "AI skill ask task processing finished": "finished",
}


def message_id_matches_chat(value: object, chat_id: str) -> bool:
    return isinstance(value, str) and (
        UUID_RE.fullmatch(value) is not None
        or (value.startswith(chat_id[-10:] + "-") and UUID_RE.fullmatch(value[11:]) is not None)
    )


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("invalid_utc")
    return result


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def size(value: object) -> int:
    """Conservatively count shared keys repeatedly within the storage budget."""
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(size(k) + size(v) for k, v in value.items())
    elif isinstance(value, (tuple, list)):
        total += sum(size(v) for v in value)
    return total


class StructureLimit(ValueError):
    pass


def bounded_json(raw: bytes, *, containers=96, separators=256, depth=12):
    """Bound decoder allocations before decoding ignored, potentially hostile fields."""
    quoted = escaped = False
    nesting = count = fields = 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            nesting += 1
            count += 1
            if nesting > depth or count > containers:
                raise StructureLimit("json_structure_limit")
        elif byte in (125, 93):
            nesting -= 1
        elif byte in (44, 58):
            fields += 1
            if fields > separators:
                raise StructureLimit("json_structure_limit")
    return json.loads(raw)


def parse_line(raw: bytes) -> dict | None:
    match = re.fullmatch(rb"(api|ai-worker)-[0-9]+\s+\|\s+(\S+)\s+(\{.*\})", raw)
    if not match:
        return None
    try:
        timestamp = utc(match[2].decode()).isoformat()
        record = bounded_json(match[3])
        message = record.get("message")
        logger = record.get("name")
        if not isinstance(message, str):
            return None
    except StructureLimit:
        raise
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return None
    event = {"utc": timestamp, "service": match[1].decode()}
    if logger == API_LOGGER and event["service"] == "api":
        applied = re.fullmatch(rf"Applied dev E2E test mock marker for message ({MESSAGE_ID})", message)
        dispatch = re.fullmatch(
            rf"\[PERF\] In-process ai\.ask dispatch took [0-9.]{{1,12}}s, "
            rf"Task ID: ({UUID}|None) for user_id=[^,\r\n]{{1,128}}, "
            rf"chat_id=({UUID}), message_id=({MESSAGE_ID})", message,
        )
        if applied:
            return {**event, "event": "api_marker_applied", "message_id": applied[1]}
        if dispatch:
            if not message_id_matches_chat(dispatch[3], dispatch[2]):
                return None
            result = {**event, "event": "api_dispatch", "chat_id": dispatch[2], "message_id": dispatch[3]}
            if dispatch[1] != "None":
                result["task_id"] = dispatch[1]
            return result
    if event["service"] != "ai-worker":
        return None
    if logger == ASK_LOGGER:
        task = re.match(rf"^\[Task ID: ({UUID})\] (.*)", message, re.S)
        if not task:
            return None
        event["task_id"] = task[1]
        context = re.match(r"LIVE MOCK: group='([A-Za-z0-9_-]{1,80})'", task[2])
        if context:
            return {**event, "event": "worker_mock", "group": context[1] if context[1] in CASES.values() else "other_group"}
        for prefix, stage in STAGES.items():
            if task[2].startswith(prefix):
                return {**event, "event": stage}
        if record.get("level") in {"ERROR", "CRITICAL"}:
            # Only an explicitly task-bound error may contribute source frames.
            exception = record.get("exc_info")
            trace = message + "\n" + (exception if isinstance(exception, str) else "")
            frame = exception_class = None
            for found in re.finditer(r'File "/app/(backend/[A-Za-z0-9_/]{1,180}\.py)", line ([0-9]{1,6}), in ([A-Za-z_][A-Za-z_0-9]{0,79})', trace):
                frame = found.groups()
            for found in re.finditer(r"(?m)^([A-Za-z_][A-Za-z_0-9.]{0,79}(?:Error|Exception)|MockCacheMiss):", trace):
                exception_class = found[1]
            if frame or exception_class:
                result = {**event, "event": "worker_exception"}
                if frame:
                    file, line, function = frame
                    result["frame"] = {"file": file, "line": int(line), "function": function}
                if exception_class:
                    result["exception_class"] = exception_class
                return result
    if logger == CELERY_LOGGER:
        lifecycle = re.match(
            rf"^\[TASK_LIFECYCLE\] (TASK_STARTED|TASK_COMPLETED|TASK_FAILED|TASK_SUCCESS): "
            rf"task_id=({UUID}), task_name=apps\.ai\.tasks\.skill_ask(?:,|$)", message,
        )
        if lifecycle:
            result = {**event, "task_id": lifecycle[2], "event": lifecycle[1].lower()}
            failure = re.search(r"(?:^|, )exception_type=([A-Za-z_][A-Za-z_0-9]{0,79}), exception_msg=redacted$", message)
            if lifecycle[1] == "TASK_FAILED" and failure:
                result["exception_class"] = failure[1]
            return result
    return None


class Reducer:
    def __init__(self):
        self.events: list[dict] = []
        self.contexts: set[tuple[str, str]] = set()
        self.flags: set[str] = set()
        self.bytes = 0
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, chunk: bytes) -> None:
        for part in chunk.splitlines(keepends=True):
            end = part.endswith(b"\n")
            if not self.dropping and len(self.buffer) + len(part) <= MAX_LINE:
                self.buffer.extend(part)
            else:
                self.flags.add("line_limit")
                self.buffer.clear()
                self.dropping = True
            if end:
                if not self.dropping:
                    try:
                        event = parse_line(bytes(self.buffer).rstrip(b"\r\n"))
                    except StructureLimit:
                        self.flags.add("json_structure_limit")
                        event = None
                    if event:
                        self.add(event)
                self.buffer.clear()
                self.dropping = False

    def add(self, event: dict) -> None:
        contexts = {(key, value) for key, value in event.items() if key in {"chat_id", "task_id", "message_id"}}
        cost = size(event) + size(contexts)
        if len(self.contexts | contexts) > MAX_CONTEXTS:
            self.flags.add("context_limit")
        elif len(self.events) >= MAX_EVENTS:
            self.flags.add("event_limit")
        elif self.bytes + cost > MAX_STORE:
            self.flags.add("memory_limit")
        else:
            self.contexts.update(contexts)
            self.events.append(event)
            self.bytes += cost


def read_attachment(result: dict, root: Path, title: str, retry: int) -> dict:
    available = result.get("attachments", [])
    if not isinstance(available, list) or len(available) > 16:
        raise ValueError("attachment_limit")
    attachments = [item for item in available if item.get("name") == ATTACHMENT]
    if len(attachments) != 1 or attachments[0].get("contentType") != "application/json":
        raise ValueError("attachment_missing")
    path = Path(attachments[0].get("path", ""))
    if not path.is_absolute():
        raise ValueError("attachment_path")
    relative = path.relative_to(root.absolute())
    if not relative.parts or any(part in {"..", "."} for part in relative.parts):
        raise ValueError("attachment_path")
    # Walk from a trusted output root using NOFOLLOW on every opened component.
    if any(parent.is_symlink() for parent in (root, *root.parents)):
        raise ValueError("attachment_path")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        child = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            import stat
            if not stat.S_ISREG(os.fstat(child).st_mode):
                raise ValueError("attachment_path")
            raw = os.read(child, MAX_BROWSER + 1)
        finally:
            os.close(child)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_BROWSER:
        raise ValueError("attachment_limit")
    data = bounded_json(raw, containers=80, separators=1200, depth=6)
    if (set(data) != {"schema", "title", "retry", "group", "chat_id", "flags", "events"}
            or data["schema"] != 1 or data["title"] != title or type(data["retry"]) is not int
            or data["retry"] != retry or data["group"] != CASES[title]
            or not isinstance(data["chat_id"], str) or not UUID_RE.fullmatch(data["chat_id"])
            or data["flags"] != [] or not isinstance(data["events"], list) or len(data["events"]) > 64):
        raise ValueError("attachment_contract")
    return data


def attempt_summary(result: dict, title: str, root: Path, capture) -> dict:
    retry, duration = result.get("retry"), result.get("duration")
    if type(retry) is not int or retry not in {0, 1} or type(duration) is not int or not 0 <= duration <= 600_000:
        raise ValueError("window_invalid")
    start = utc(result["startTime"]) - timedelta(seconds=2)
    end = start + timedelta(milliseconds=duration, seconds=7)
    summary = {"title": title, "attempt": retry, "since": start.isoformat(), "until": end.isoformat(), "status": "incomplete", "reasons": []}
    if start < utc(capture.started) or capture.ended is None or end > utc(capture.ended):
        summary["reasons"].append("window_not_covered")
    browser = read_attachment(result, root, title, retry)
    message_ids, announced, turns = set(), set(), set()
    browser_events = []
    for item in browser["events"]:
        if (not isinstance(item, dict) or set(item) - {"utc", "direction", "event", "chat_id", "message_id", "turn_id", "task_id", "marker_present", "expected_group_match"}
                or item.get("chat_id") != browser["chat_id"] or not start <= utc(item["utc"]) <= end):
            raise ValueError("browser_event_invalid")
        if any(not (message_id_matches_chat(value, browser["chat_id"]) if key == "message_id"
                    else isinstance(value, str) and UUID_RE.fullmatch(value))
               for key, value in item.items() if key.endswith("_id")):
            raise ValueError("browser_event_invalid")
        if item.get("event") in OUTGOING and item.get("direction") == "sent":
            if (type(item.get("marker_present")) is not bool or type(item.get("expected_group_match")) is not bool or not item.get("message_id")
                    or "task_id" in item or (item["expected_group_match"] and not item["marker_present"])):
                raise ValueError("browser_event_invalid")
            message_ids.add(item["message_id"])
            if "turn_id" in item:
                turns.add(item["turn_id"])
        elif item.get("event") == "ai_task_initiated" and item.get("direction") == "received" and item.get("task_id"):
            if set(item) - {"utc", "direction", "event", "chat_id", "message_id", "task_id"} or not item.get("message_id"):
                raise ValueError("browser_event_invalid")
            announced.add(item["task_id"])
        else:
            raise ValueError("browser_event_invalid")
        browser_events.append(item)
    if len(message_ids) != 1 or len(announced) > 1 or len(turns) > 1:
        raise ValueError("browser_correlation_ambiguous")
    message_id = next(iter(message_ids))
    if any(item.get("message_id") != message_id for item in browser_events):
        raise ValueError("browser_correlation_ambiguous")
    dispatches = [event for event in capture.reducer.events if start <= utc(event["utc"]) <= end
                  and event.get("event") == "api_dispatch" and event.get("chat_id") == browser["chat_id"] and event.get("message_id") == message_id]
    tasks = {event["task_id"] for event in dispatches if event.get("task_id")}
    if len(tasks) > 1 or (announced and tasks and announced != tasks):
        raise ValueError("server_correlation_ambiguous")
    task_id = next(iter(tasks or announced), None)
    events = [event for event in capture.reducer.events if start <= utc(event["utc"]) <= end and (
        (event.get("event") == "api_marker_applied" and event.get("message_id") == message_id)
        or event in dispatches or (task_id is not None and event["service"] == "ai-worker" and event.get("task_id") == task_id))]
    if len(events) + len(browser_events) > 128:
        events = events[:128 - len(browser_events)]
        summary["reasons"].append("attempt_event_limit")
    events.sort(key=lambda event: utc(event["utc"]))
    observed = {event["event"] for event in events}
    mock = any(event.get("event") == "worker_mock" and event.get("group") == CASES[title] for event in events)
    transported = any(item.get("marker_present") and item.get("expected_group_match") for item in browser_events)
    for present, reason in ((transported, "browser_marker_not_observed"),
                            ("api_marker_applied" in observed, "api_marker_not_observed"),
                            (bool(tasks), "dispatch_not_observed"), (mock, "expected_worker_context_not_observed")):
        if not present:
            summary["reasons"].append(reason)
    summary.update(chat_id=browser["chat_id"], message_id=message_id, task_id=task_id,
                   task_origin="api_dispatch" if tasks else "browser_announcement" if announced else "not_observed",
                   api_marker="observed" if "api_marker_applied" in observed else "not_observed",
                   worker_context="observed" if mock else "not_observed", browser=browser_events, events=events)
    summary["status"] = "incomplete" if summary["reasons"] or capture.reducer.flags else "complete"
    return summary


class Capture:
    def __init__(self, root: Path, provenance: dict):
        self.root, self.provenance = root, provenance
        self.reducer = Reducer()
        self.started, self.ended = now(), None
        self.process = self.reader = self.timer = None
        self.stopping = threading.Event()
        self.lock = threading.Lock()

    def start(self) -> None:
        try:
            try:
                from ci_environment import COMPOSE_PATH, SOURCE, require_runner
            except ModuleNotFoundError:
                from scripts.ci_environment import COMPOSE_PATH, SOURCE, require_runner
            require_runner()
            if os.environ.get("OPENMATES_CI_ISOLATED") != "1" or Path(SOURCE).resolve() != self.root.resolve():
                raise ValueError("isolation")
            if (not re.fullmatch(r"[0-9a-f]{40}", self.provenance.get("source_commit", ""))
                    or not re.fullmatch(r"[0-9a-f]{40}", self.provenance.get("harness_commit", ""))
                    or not re.fullmatch(r"[0-9]{1,20}", self.provenance.get("run_id", ""))):
                raise ValueError("provenance")
            self.process = subprocess.Popen(
                ["docker", "compose", "-f", str(COMPOSE_PATH), "logs", "--follow", "--no-color", "--timestamps", "--since", self.started, "api", "ai-worker"],
                cwd=SOURCE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.timer = threading.Timer(MAX_SECONDS, lambda: self.stop("time_limit"))
            self.timer.daemon = True
            self.timer.start()
        except Exception:
            self.reducer.flags.add("capture_start_failed")
            self.stop()

    def _read(self) -> None:
        try:
            while chunk := self.process.stdout.read1(8192):
                if self.stopping.is_set():
                    break
                self.reducer.feed(chunk)
            if not self.stopping.is_set():
                self.reducer.flags.add("stream_ended_early")
        except Exception:
            if not self.stopping.is_set():
                self.reducer.flags.add("stream_read_failed")

    def stop(self, reason: str | None = None) -> None:
        with self.lock:
            if reason:
                self.reducer.flags.add(reason)
            if self.stopping.is_set():
                return
            self.stopping.set()
            self.ended = now()
            if self.timer:
                self.timer.cancel()
            if self.process:
                try:
                    if self.process.poll() is None:
                        (self.process.kill if reason == "time_limit" else self.process.terminate)()
                except Exception:
                    self.reducer.flags.add("capture_stop_failed")
                    try:
                        self.process.kill()
                    except Exception:
                        pass
                try:
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=2)
                except Exception:
                    self.reducer.flags.add("capture_stop_failed")
                    try:
                        self.process.kill()
                        self.process.wait(timeout=2)
                    except Exception:
                        self.reducer.flags.add("process_not_reaped")
                try:
                    self.process.stdout.close()
                except Exception:
                    self.reducer.flags.add("capture_stop_failed")
            if self.reader:
                try:
                    self.reader.join(timeout=2)
                    if self.reader.is_alive():
                        self.reducer.flags.add("reader_not_stopped")
                except Exception:
                    self.reducer.flags.add("capture_stop_failed")

    def summarize(self, report: dict, attachment_root: Path) -> dict:
        provenance = {key: value if isinstance(value, str) and re.fullmatch(pattern, value) else "invalid"
                      for key, pattern in (("source_commit", r"[0-9a-f]{40}"), ("harness_commit", r"[0-9a-f]{40}"), ("run_id", r"[0-9]{1,20}"))
                      for value in (self.provenance.get(key),)}
        if "invalid" in provenance.values():
            self.reducer.flags.add("provenance_invalid")
        result = {**provenance, "schema": 1, "spec": SPEC, "status": "not_needed", "capture_flags": sorted(self.reducer.flags), "attempts": []}
        try:
            pending, nodes, seen = [(report, 0)], 0, set()
            while pending:
                node, depth = pending.pop()
                nodes += 1
                if nodes > 128 or depth > 6:
                    raise ValueError("report_limit")
                for spec in node.get("specs", []):
                    nodes += 1
                    if nodes > 128:
                        raise ValueError("report_limit")
                    title = spec.get("title")
                    if title not in CASES:
                        continue
                    if Path(spec.get("file", "")).name != SPEC or ".." in Path(spec.get("file", "")).parts:
                        raise ValueError("report_scope")
                    for test in spec.get("tests", []):
                        nodes += 1
                        if nodes > 128:
                            raise ValueError("report_limit")
                        for item in test.get("results", []):
                            nodes += 1
                            if nodes > 128:
                                raise ValueError("report_limit")
                            if item.get("status") not in {"failed", "timedOut"}:
                                continue
                            key = (title, item.get("retry"))
                            if key in seen or len(seen) >= 4:
                                raise ValueError("attempt_limit")
                            seen.add(key)
                            try:
                                summary = attempt_summary(item, title, attachment_root, self)
                            except Exception:
                                summary = {"title": title, "status": "incomplete", "reasons": ["invalid_or_missing_attempt_evidence"]}
                            result["attempts"].append(summary)
                children = node.get("suites", [])
                if not isinstance(children, list) or len(children) > 128 - nodes - len(pending):
                    raise ValueError("report_limit")
                pending.extend((child, depth + 1) for child in children)
            if result["attempts"]:
                result["status"] = "incomplete" if self.reducer.flags or any(item["status"] != "complete" for item in result["attempts"]) else "complete"
            elif self.reducer.flags:
                result["status"] = "incomplete"
            if len(encoded(result)) > MAX_OUTPUT:
                raise ValueError("output_limit")
        except Exception:
            result.update(status="incomplete", attempts=[], capture_flags=sorted(self.reducer.flags | {"summary_invalid_or_limited"}))
        return result

    def persist_interrupted(self, index: int) -> None:
        """Keep only an incomplete receipt if Playwright raises before a report."""
        try:
            if type(index) is not int or not 0 <= index <= 999:
                return
            root = self.root / "test-results"
            if any(parent.is_symlink() for parent in (root, *root.parents)):
                return
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                descriptor = os.open(f"ci-spec-{index}-web-search-diagnostics.json",
                                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded(self.summarize({}, root)))
            finally:
                os.close(parent)
        except Exception:
            self.reducer.flags.add("interrupted_receipt_failed")


def start_capture(name: str, root: Path, *, enabled: bool) -> Capture | None:
    if not enabled or name != SPEC or os.environ.get("CI_TEST_MODE") != "e2e":
        return None
    provenance = {"source_commit": "", "harness_commit": os.environ.get("CI_HARNESS_COMMIT", ""), "run_id": os.environ.get("GITHUB_RUN_ID", "")}
    capture = Capture(root, provenance)
    try:
        provenance["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10).strip()
        capture.start()
    except Exception:
        capture.reducer.flags.add("capture_start_failed")
        capture.stop()
    return capture


@contextmanager
def capture_scope(name: str, root: Path, index: int, *, enabled: bool):
    capture = start_capture(name, root, enabled=enabled)
    interrupted = False
    try:
        yield capture
    except BaseException:
        interrupted = True
        if capture:
            capture.reducer.flags.add("playwright_interrupted")
        raise
    finally:
        if capture:
            capture.stop()
            if interrupted:
                capture.persist_interrupted(index)
