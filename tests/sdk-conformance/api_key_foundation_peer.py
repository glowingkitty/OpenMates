"""Shared wire oracle reuses frozen App18 peer; no product execution on dev."""

from copy import deepcopy
import json
import threading
from session_direct_app_skill_peer import DirectSkillPeer


class ApiKeyFoundationPeer(DirectSkillPeer):
    def __init__(self, suite, vector, identity):
        self.code_arrived = threading.Event()
        self.code_b_sent = threading.Event()
        self.code_a_headers_sent = threading.Event()
        self.code_terminal = False
        self.code_release_verified = False
        self.parallel_arrived = threading.Event()
        self.parallel_b_sent = threading.Event()
        self.parallel_a_headers_sent = threading.Event()
        self.parallel_terminal = False
        self.parallel_release_verified = False
        self.original_vector = vector
        wire = deepcopy(vector)
        wire["mode"] = vector.get("wire_mode", vector["mode"])
        super().__init__(suite, wire, identity)
        self.counts["account_reads"] = 0

    def status(self):
        return {
            **super().status(),
            "parallel_all_arrived": self.parallel_arrived.is_set(),
            "parallel_b_sent": self.parallel_b_sent.is_set(),
            "parallel_a_headers_sent": self.parallel_a_headers_sent.is_set(),
            "parallel_terminal": self.parallel_terminal,
            "parallel_release_verified": self.parallel_release_verified,
            "a_released": self.release.is_set(),
            "code_all_arrived": self.code_arrived.is_set(),
            "code_b_sent": self.code_b_sent.is_set(),
            "code_a_headers_sent": self.code_a_headers_sent.is_set(),
            "code_terminal": self.code_terminal,
            "code_release_verified": self.code_release_verified,
        }

    def handler(self):
        base = super().handler()
        peer = self

        class Handler(base):
            def dispatch(self, method):
                mode = peer.original_vector["mode"]
                code_parallel = mode in {
                    "parallel_code_success",
                    "parallel_code_failed_status",
                    "parallel_code_http_failure",
                }
                if code_parallel and self.path == "/__test/code-terminal":
                    assert method == "GET" and mode == "parallel_code_http_failure"
                    assert peer.code_arrived.is_set() and peer.code_b_sent.is_set()
                    assert not peer.release.is_set(), (
                        "typed HTTP failure must reach caller while A body held"
                    )
                    peer.code_terminal = True
                    self.response(200, {"terminal_while_a_held": True})
                    return
                if code_parallel and self.path == "/__test/release":
                    assert (
                        method == "GET"
                        and peer.code_arrived.is_set()
                        and peer.code_b_sent.is_set()
                    )
                    if mode == "parallel_code_http_failure":
                        assert peer.code_terminal
                    peer.code_release_verified = True
                    peer.release.set()
                    self.response(200, {"released": True})
                    return
                if code_parallel and self.path == "/v1/apps/code/skills/run":
                    peer.headers(self)
                    assert method == "POST"
                    n = int(self.headers.get("Content-Length", "0"))
                    assert 0 < n <= 1024 * 1024
                    body = json.loads(self.rfile.read(n))
                    assert body == peer.original_vector["request"]["input"]
                    with peer.lock:
                        peer.counts["skill_posts"] += 1
                        assert peer.counts["skill_posts"] == 1, (
                            "one paid POST; no retry"
                        )
                        peer.bodies.append(body)
                    self.response(
                        200,
                        {
                            "success": True,
                            "credits_charged": len(
                                peer.original_vector["original_code_ids"]
                            ),
                            "data": {
                                "batch": "code-fixture",
                                "results": peer.original_vector["code_results"],
                            },
                        },
                    )
                    return
                if code_parallel and self.path.startswith("/v1/code/run/"):
                    peer.headers(self)
                    assert method == "GET"
                    paths = peer.original_vector["original_status_paths"]
                    ids = peer.original_vector["original_code_ids"]
                    assert self.path in paths, (
                        "only original status paths; no invented jobs"
                    )
                    index = paths.index(self.path)
                    job = ids[index]
                    with peer.lock:
                        peer.polls[job] = peer.polls.get(job, 0) + 1
                        assert peer.polls[job] == 1, (
                            "one terminal poll per original code job"
                        )
                        peer.poll_order.append(job)
                        if set(peer.polls) == set(ids):
                            peer.code_arrived.set()
                    assert peer.code_arrived.wait(15), (
                        "all four original status GETs must arrive before A release"
                    )
                    if index == 1:
                        assert peer.code_a_headers_sent.wait(15), (
                            "actual A headers sent, body held before B response"
                        )
                    if index == 1 and mode == "parallel_code_http_failure":
                        self.response(
                            403, {"detail": "synthetic-private-server-diagnostic"}
                        )
                    elif index == 0:
                        raw = json.dumps(
                            peer.original_vector["code_statuses"][0]
                        ).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.flush()
                        peer.code_a_headers_sent.set()
                        assert peer.release.wait(15), (
                            "actual A status response body held until explicit release"
                        )
                        try:
                            self.wfile.write(raw)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    else:
                        try:
                            self.response(
                                200, peer.original_vector["code_statuses"][index]
                            )
                        except (BrokenPipeError, ConnectionResetError):
                            if mode != "parallel_code_http_failure":
                                raise
                    if index == 1:
                        self.wfile.flush()
                        peer.code_b_sent.set()
                    return
                parallel = mode in {"parallel_tasks_success", "parallel_tasks_failure"}
                single = mode.startswith(("task_ids_one_", "task_id_direct_"))
                if parallel and self.path == "/__test/parallel-terminal":
                    assert method == "GET" and mode == "parallel_tasks_failure"
                    assert (
                        peer.parallel_arrived.is_set() and peer.parallel_b_sent.is_set()
                    )
                    assert not peer.release.is_set(), (
                        "typed failure must reach caller while A body held"
                    )
                    peer.parallel_terminal = True
                    self.response(200, {"terminal_while_a_held": True})
                    return
                if parallel and self.path == "/__test/release":
                    assert method == "GET"
                    assert (
                        peer.parallel_arrived.is_set() and peer.parallel_b_sent.is_set()
                    ), "all original GETs and B response before A release"
                    if mode == "parallel_tasks_failure":
                        assert peer.parallel_terminal
                    peer.parallel_release_verified = True
                    peer.release.set()
                    self.response(200, {"released": True})
                    return
                if (parallel or single) and self.path == "/v1/apps/web/skills/search":
                    peer.headers(self)
                    assert method == "POST"
                    n = int(self.headers.get("Content-Length", "0"))
                    assert 0 < n <= 1024 * 1024
                    body = json.loads(self.rfile.read(n))
                    with peer.lock:
                        peer.validate_input(body)
                        peer.counts["skill_posts"] += 1
                        assert peer.counts["skill_posts"] == 1, (
                            "one paid POST; no retries"
                        )
                        peer.bodies.append(body)
                    ids = peer.original_vector["original_task_ids"]
                    data = (
                        {"task_ids": ids}
                        if parallel or mode.startswith("task_ids_one_")
                        else {"task_id": ids[0]}
                    )
                    self.response(
                        200,
                        {"success": True, "credits_charged": len(ids), "data": data},
                    )
                    return
                if (parallel or single) and self.path.startswith("/v1/tasks/"):
                    peer.headers(self)
                    assert method == "GET"
                    task = self.path.removeprefix("/v1/tasks/")
                    ids = peer.original_vector["original_task_ids"]
                    assert task in ids, (
                        "only original IDs; no replacement or invented tasks"
                    )
                    with peer.lock:
                        peer.polls[task] = peer.polls.get(task, 0) + 1
                        assert peer.polls[task] == 1, (
                            "terminal original task must not be retried"
                        )
                        peer.poll_order.append(task)
                        if parallel and set(peer.polls) == set(ids):
                            peer.parallel_arrived.set()
                    if single:
                        self.response(
                            200,
                            {
                                "task_id": task,
                                "status": "completed",
                                "result": peer.original_vector["task_result"],
                            },
                        )
                        return
                    assert peer.parallel_arrived.wait(15), (
                        "all four original GETs must arrive concurrently while A held"
                    )
                    if task == "task_b":
                        assert peer.parallel_a_headers_sent.wait(15), (
                            "A actual headers sent with body held before B response"
                        )
                    if task == "task_b" and mode == "parallel_tasks_failure":
                        self.response(
                            200,
                            {
                                "task_id": task,
                                "status": "failed",
                                "error": "synthetic-private-server-diagnostic",
                            },
                        )
                    elif task == "task_a":
                        raw = json.dumps(
                            {
                                "task_id": task,
                                "status": "completed",
                                "result": peer.original_vector["task_results"][0],
                            }
                        ).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.flush()
                        peer.parallel_a_headers_sent.set()
                        assert peer.release.wait(15), (
                            "actual A response body held until explicit release"
                        )
                        try:
                            self.wfile.write(raw)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    else:
                        self.response(
                            200,
                            {
                                "task_id": task,
                                "status": "completed",
                                "result": peer.original_vector["task_results"][
                                    ids.index(task)
                                ],
                            },
                        )
                    if task == "task_b":
                        self.wfile.flush()
                        peer.parallel_b_sent.set()
                    return
                if self.path == "/v1/sdk/account":
                    peer.headers(self)
                    assert method == "GET"
                    with peer.lock:
                        peer.counts["account_reads"] += 1
                        assert (
                            peer.counts["account_reads"]
                            <= peer.original_vector["expected_account_reads"]
                        )
                    if peer.original_vector["mode"] == "account_auth_refusal":
                        self.response(
                            403, {"detail": "synthetic-private-server-diagnostic"}
                        )
                    else:
                        self.response(200, peer.suite["account_expected"])
                    return
                super().dispatch(method)

        return Handler
