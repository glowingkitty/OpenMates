# backend/tests/test_s3_service_no_sync_boto3_in_async.py
#
# Static (AST) guard against a class of bug that took prod down on 2026-04-06:
# calling synchronous boto3 client methods (e.g. self.client.delete_object,
# self.client.get_object, self.client.put_object) directly from inside an
# `async def` method of S3UploadService. Every such call blocks the event
# loop for the full duration of the network round-trip (and any boto3 retry
# backoff). Under S3 SlowDown throttling that stalled login requests to 60+
# seconds — see commit d64b91773 and the auto_delete_old_usage incident.
#
# The correct pattern is to wrap the sync boto3 call in asyncio.to_thread(...)
# (or an equivalent executor call) so the event loop stays responsive.
#
# This test walks the AST of backend/core/api/app/services/s3/service.py and
# fails if any S3UploadService async method contains a direct call to
# `self.client.<method>()` or `<name>.put_object/get_object/delete_object(...)`
# that is NOT wrapped in asyncio.to_thread / loop.run_in_executor.

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set, Tuple

SERVICE_FILE = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "api"
    / "app"
    / "services"
    / "s3"
    / "service.py"
)

# boto3 S3 client methods that perform blocking network I/O and must be
# awaited via a thread pool when called from async code. This is not an
# exhaustive list of boto3 methods — only the ones the service currently uses
# or is likely to use. Add more here if upload_file / get_file / delete_file
# ever grows new code paths.
BLOCKING_BOTO3_METHODS: Set[str] = {
    "put_object",
    "get_object",
    "delete_object",
    "head_object",
    "copy_object",
    "upload_fileobj",
    "download_fileobj",
    "list_objects_v2",
    "delete_objects",
}

# Methods in S3UploadService that are synchronous by design (not async def)
# and therefore are allowed to call blocking boto3 methods directly. These
# are invoked from blocking contexts (init, presigned URL generation) where
# event-loop blocking is not a concern. Keep this list tight.
SYNC_METHODS_ALLOWED: Set[str] = {
    "_initialize_buckets",  # runs once at startup
    "generate_presigned_url",  # sync helper, no network I/O in the call itself
}


def _is_to_thread_call(node: ast.AST) -> bool:
    """True if node is `asyncio.to_thread(...)` or `asyncio.get_running_loop().run_in_executor(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # asyncio.to_thread(...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "to_thread"
        and isinstance(func.value, ast.Name)
        and func.value.id == "asyncio"
    ):
        return True
    # <anything>.run_in_executor(...)
    if isinstance(func, ast.Attribute) and func.attr == "run_in_executor":
        return True
    return False


def _iter_direct_body_nodes(method: ast.AsyncFunctionDef):
    """
    Yield every AST node that is part of the method's *own* direct execution
    context — i.e. not the body of a nested FunctionDef / AsyncFunctionDef /
    Lambda / comprehension-with-its-own-scope inside the method.

    Nested function bodies are intentionally skipped because their code does
    not execute in the async method's event loop directly: they are invoked
    by whoever calls the closure (typically `asyncio.to_thread(_download)`
    runs the closure in the default thread pool, which is safe).
    """
    # Use a manual walk so we can prune entire subtrees when we hit a nested
    # function definition. `ast.walk` cannot prune.
    stack: List[ast.AST] = list(method.body)
    while stack:
        node = stack.pop()
        yield node
        # Do NOT descend into nested function/lambda bodies — they have their
        # own call context.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _find_sync_boto3_violations_in_async_method(
    method: ast.AsyncFunctionDef,
) -> List[Tuple[int, str]]:
    """
    Walk an async method body and return a list of (lineno, description)
    for every call to a known blocking boto3 method that is NOT wrapped in
    asyncio.to_thread / run_in_executor.

    Nested function bodies (closures) are intentionally NOT scanned because
    their code runs in whatever context the closure is invoked from — the
    canonical safe pattern is:

        async def get_file(...):
            def _download() -> bytes:
                return self.client.get_object(...)[...]
            return await asyncio.to_thread(_download)
    """
    violations: List[Tuple[int, str]] = []

    # Build parent map but only for the nodes that belong to the method's own
    # execution context (not nested functions).
    own_nodes = list(_iter_direct_body_nodes(method))
    parent_map: dict[int, ast.AST] = {}
    for parent in own_nodes:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        for child in ast.iter_child_nodes(parent):
            parent_map[id(child)] = parent

    for node in own_nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `<something>.<blocking_method>(...)`.
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in BLOCKING_BOTO3_METHODS:
            continue

        # Check if any ancestor Call is asyncio.to_thread / run_in_executor.
        wrapped = False
        cursor: ast.AST = node
        while id(cursor) in parent_map:
            cursor = parent_map[id(cursor)]
            if _is_to_thread_call(cursor):
                wrapped = True
                break

        if not wrapped:
            violations.append(
                (
                    node.lineno,
                    f"{ast.unparse(func)}(...) called without asyncio.to_thread",
                )
            )

    return violations


def test_s3_service_file_exists():
    """Sanity check: the service file we're scanning actually exists."""
    assert SERVICE_FILE.is_file(), f"S3 service file not found at {SERVICE_FILE}"


def test_no_sync_boto3_calls_in_async_methods():
    """
    AST guard: assert that every `async def` in S3UploadService routes its
    blocking boto3 calls through asyncio.to_thread (or run_in_executor).

    Regression test for the auto_delete_old_usage S3 delete storm incident
    (commit d64b91773). Before the fix, delete_file / get_file / upload_file
    all called sync boto3 methods directly inside async functions, blocking
    the API event loop under S3 backpressure and stalling login requests to
    60+ seconds.
    """
    tree = ast.parse(SERVICE_FILE.read_text(), filename=str(SERVICE_FILE))

    # Find the S3UploadService class.
    service_class: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "S3UploadService":
            service_class = node
            break
    assert service_class is not None, "S3UploadService class not found in service.py"

    # Collect all violations across all async methods.
    all_violations: List[str] = []
    for member in service_class.body:
        if not isinstance(member, ast.AsyncFunctionDef):
            continue
        if member.name in SYNC_METHODS_ALLOWED:
            continue  # (async-named but whitelisted; none currently)
        violations = _find_sync_boto3_violations_in_async_method(member)
        for lineno, desc in violations:
            all_violations.append(
                f"S3UploadService.{member.name} (line {lineno}): {desc}"
            )

    assert not all_violations, (
        "Found sync boto3 calls inside async methods of S3UploadService. "
        "These block the event loop under S3 backpressure (see commit "
        "d64b91773 — auto_delete_old_usage storm). Wrap each blocking call "
        "in `await asyncio.to_thread(self.client.<method>, ...)`. Offenders:\n  - "
        + "\n  - ".join(all_violations)
    )


def test_known_async_methods_are_covered():
    """
    Meta-test: if S3UploadService gains a new async method in the future,
    this test fails loudly so the author is prompted to confirm it doesn't
    introduce a new sync-boto3-in-async regression path.

    Update KNOWN_ASYNC_METHODS when adding a new async method after
    verifying it either (a) does not call boto3 at all, or (b) wraps every
    boto3 call in asyncio.to_thread.
    """
    KNOWN_ASYNC_METHODS: Set[str] = {
        "initialize",
        "_initialize_buckets",
        "upload_file",
        "delete_file",
        "get_file",
    }

    tree = ast.parse(SERVICE_FILE.read_text(), filename=str(SERVICE_FILE))
    service_class: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "S3UploadService":
            service_class = node
            break
    assert service_class is not None

    actual_async_methods: Set[str] = {
        m.name for m in service_class.body if isinstance(m, ast.AsyncFunctionDef)
    }

    new_methods = actual_async_methods - KNOWN_ASYNC_METHODS
    assert not new_methods, (
        f"New async method(s) detected in S3UploadService: {sorted(new_methods)}. "
        "Verify each new method either does not call boto3 at all, or wraps "
        "every boto3 client call in `await asyncio.to_thread(...)`. Then add "
        "the method name to KNOWN_ASYNC_METHODS in this test."
    )
