"""Closed, bounded observations of existing migration CI failure rows.

Only trusted producer suite/stage/code enums may enter ordinary runner logs.
No raw diagnostics, candidate text, identifiers or source coordinates are read.
This helper performs no IO and grants no proof or acceptance of a failed run.
Unknown or malformed fields never gain authority through string conversion.
The caller isolates optional serialization/log failures from report/exit logic.
"""

import json

MAX_SCANNED_ROWS = 32
MAX_FAILURE_ROWS = 8
MAX_ROW_KEYS = 16
MAX_ENUM_LENGTH = 64
MAX_JSON_BYTES = 4096

# Reviewed fixed producer stages/codes, deliberately independent of candidate
# modules. New producer values require review; never import or derive at runtime.
_SDK_STAGES = frozenset({
    "admission", "rust-toolchain", "python-environment", "node-dependencies",
    "python-dependencies", "sdk-library-units", "binding-library-units",
    "napi-build", "python-binding-build", "sdk-facade-build", "napi-load",
    "python-load", "real-conformance", "final-fences",
})
_SDK_CODES = frozenset("""
artifact_changed artifact_reserve changed_file child_failed
command_executable_alias_changed command_executable_bound
command_executable_fd_changed command_executable_missing
command_executable_not_executable command_executable_not_regular
command_executable_open command_executable_owner command_executable_size
command_executable_world_writable command_identity command_python_kernel_mismatch
command_python_kernel_unavailable command_python_not_elf deadline deadline_identity
 diagnostic_bound diagnostic_file dist_changed exact_sdk_target_required gate_fixture
 gate_identity gate_incomplete gate_launches gate_matrix gate_result_identity
 gate_result_vectors gate_reviewed_expectations gate_reviewed_matrix gate_vectors
 github_runner_required invalid_native_artifact napi_preservation native_architecture
 npm_setup_missing preexisting_native_artifact private_boundary
 python_or_node_attestation python_preservation reviewed_contract_changed
 reviewed_program_changed runner_architecture sdk_dependency_contract sdk_dist_missing
 setup_tools_missing source_batch_bound source_batch_tail source_blob_bound
 source_blob_identity source_blob_size source_changed source_checkout_changed
 source_identity source_inputs_missing source_tree_bound source_tree_byte_bound
 source_tree_metadata source_tree_type stage_deadline unit_test_evidence unsafe_file
 untracked_source_input unclassified
""".split())
_WASM_CODES = frozenset({
    "admission", "identity", "source", "deadline", "disk", "toolchain", "compile",
    "packaging", "outputs", "cleanup", "worker", "unclassified",
})
_NATIVE_CODES = frozenset({
    "admission", "identity", "source", "deadline", "disk", "toolchain", "package",
    "fetch", "compile", "outputs", "transport", "cleanup", "unclassified",
})
_SUITES = {
    "sdk-conformance": (_SDK_STAGES, _SDK_CODES),
    # These producers do not currently add failed_stage to results. Do not infer
    # one from receipt steps, raw diagnostics, error text or their failure code.
    "rust-wasm": (frozenset(), _WASM_CODES),
    "rust-native-dev": (frozenset(), _NATIVE_CODES),
}


def _closed(value, allowed):
    if type(value) is str and len(value) <= MAX_ENUM_LENGTH and value in allowed:
        return value
    return "unclassified"


def failure_summary(results):
    """Return bounded ASCII JSON for failed allowlisted rows, otherwise None."""
    if type(results) is not list:
        return None
    failures = []
    truncated = len(results) > MAX_SCANNED_ROWS
    for index in range(min(len(results), MAX_SCANNED_ROWS)):
        row = results[index]
        if type(row) is not dict or len(row) > MAX_ROW_KEYS:
            continue
        # Reject hostile keys before any lookup; exact dict alone does not
        # prevent a custom key's equality callback during a hash collision.
        if any(type(key) is not str or len(key) > MAX_ENUM_LENGTH for key in row):
            continue
        suite = row.get("suite")
        if type(suite) is not str or len(suite) > MAX_ENUM_LENGTH or suite not in _SUITES:
            continue
        exit_code = row.get("exit_code")
        if type(exit_code) is not int or not -255 <= exit_code <= 255 or exit_code == 0:
            continue
        if len(failures) == MAX_FAILURE_ROWS:
            truncated = True
            break
        stages, codes = _SUITES[suite]
        failures.append({
            "suite": suite,
            "failed_stage": _closed(row.get("failed_stage"), stages),
            "failure_code": _closed(row.get("failure_code"), codes),
        })
    if not failures:
        return None
    summary = json.dumps({
        "kind": "migration-ci-failure-summary",
        "observation": True,
        "proofAccepted": False,
        "failures": failures,
        "truncated": truncated,
    }, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return summary if len(summary) <= MAX_JSON_BYTES else None
