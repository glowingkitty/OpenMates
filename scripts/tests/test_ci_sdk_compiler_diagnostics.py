"""Pure compiler-coordinate projection; no compiler, SDK or product execution."""
# contract-test-file: tooling
import json

import pytest

from scripts import ci_sdk_conformance as sdk


BINDING = "packages/openmates-session-bindings/src/session.rs"
CORE = "packages/openmates-rust/src/client.rs"


def project(tmp_path, text, paths=(BINDING, CORE)):
    return sdk.compiler_diagnostics(text.encode(), tmp_path, dict.fromkeys(paths, "a" * 64))


def loc(path, line, column=7):
    return {"path": path, "line": line, "column": column}


def test_warning_flood_never_hides_actual_error_primary_span(tmp_path):
    warnings = "".join(f"warning: secret-warning-{i}\n --> {CORE}:{i + 1}:2\n" for i in range(40))
    result = project(tmp_path, warnings + f"error[E0277]: secret-error\n --> {BINDING}:903:7\n")
    assert result == [{"kind": "rustc", "code": "E0277", "locations": [loc(BINDING, 903)]}]
    assert "secret" not in json.dumps(result)


def test_multiple_codes_and_repeated_code_keep_only_their_own_spans(tmp_path):
    selected = "packages/openmates-session-bindings/src/session_essential/selected_tests.rs"
    full_read = "packages/openmates-session-bindings/src/session_full_read_tests.rs"
    text = (f"error[E0277]: private-a\n --> {selected}:91:7\n"
            f"error[E0308]: private-b\n --> {full_read}:42:9\n"
            f"error[E0277]: private-c\n --> {selected}:92:7\n")
    assert project(tmp_path, text, (selected, full_read)) == [
        {"kind": "rustc", "code": "E0277", "locations": [loc(selected, 91), loc(selected, 92)]},
        {"kind": "rustc", "code": "E0308", "locations": [loc(full_read, 42, 9)]},
    ]


@pytest.mark.parametrize("boundary", ["warning: private", "warning[unused]: private", "error: private", "error[PRIVATE]: private"])
def test_non_error_diagnostics_end_own_span_collection(tmp_path, boundary):
    text = (f" --> {CORE}:1:1\nerror[E0277]: private\n --> {BINDING}:2:7\n"
            f"{boundary}\n --> {CORE}:3:1\n")
    assert project(tmp_path, text) == [{"kind": "rustc", "code": "E0277", "locations": [loc(BINDING, 2)]}]


def test_primary_spans_precede_bounded_secondary_context_and_deduplicate(tmp_path):
    text = "error[E0308]: private\n" + "".join(f" ::: {CORE}:{i + 1}:7\n" for i in range(30))
    text += f" --> {BINDING}:500:7\n --> {BINDING}:500:7\n --> {CORE}:1:7\n"
    result = project(tmp_path, text)
    assert result[0]["locations"] == [loc(BINDING, 500), loc(CORE, 1)] + [loc(CORE, i) for i in range(2, 16)]
    assert len(result[0]["locations"]) == 16


def test_later_repeated_code_primary_not_starved_by_earlier_secondary_spans(tmp_path):
    text = "error[E0277]: private\n" + "".join(f" ::: {CORE}:{i + 1}:7\n" for i in range(20))
    text += f"error[E0277]: private-again\n --> {BINDING}:600:7\n"
    assert project(tmp_path, text)[0]["locations"][0] == loc(BINDING, 600)


@pytest.mark.parametrize("style", ["root_relative", "crate_relative", "absolute", "normalized"])
def test_only_original_input_whitelisted_relative_or_absolute_paths_export(tmp_path, style):
    paths = {"root_relative": BINDING, "crate_relative": "src/session.rs",
             "absolute": str(tmp_path / BINDING),
             "normalized": "packages/openmates-session-bindings/src/../src/session.rs"}
    text = f"error[E0308]: private\n --> {paths[style]}:8:7\n"
    assert project(tmp_path, text) == [{"kind": "rustc", "code": "E0308", "locations": [loc(BINDING, 8)]}]


def test_unknown_outside_and_symlink_escape_paths_never_export(tmp_path):
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    text = ("error[E0277]: TOKEN-cookie-master-key-private-message\n"
            " --> /private/secret-token.rs:1:1\n --> ../../secret.rs:2:2\n"
            " --> unknown-token.rs:3:3\n --> escape/secret.rs:4:4\n"
            f" --> {BINDING}:9:7\n")
    result = project(tmp_path, text, (BINDING, "escape/secret.rs"))
    assert result == [{"kind": "rustc", "code": "E0277", "locations": [loc(BINDING, 9)]}]
    encoded = json.dumps(result)
    assert not any(secret in encoded for secret in ["TOKEN", "cookie", "master-key", "private-message", "secret", str(tmp_path)])


def test_code_location_and_total_limits_remain_finite(tmp_path):
    text = "".join(f"error[E{i:04}]: private\n" + "".join(f" --> {BINDING}:{j + 1}:7\n" for j in range(30)) for i in range(20))
    text += "".join(f"src/index.ts({i + 1},2): error TS2322: private\n" for i in range(30))
    result = project(tmp_path, text, (BINDING, "frontend/packages/openmates-cli/src/index.ts"))
    rust = [row for row in result if row["kind"] == "rustc"]
    assert len(result) == 32 and len(rust) == 16
    assert [row["code"] for row in rust] == [f"E{i:04}" for i in range(16)]
    assert all(len(row["locations"]) == 16 for row in rust)
    assert all(set(row) == {"kind", "code", "locations"} for row in result)
    assert all(set(position) == {"path", "line", "column"} for row in result for position in row["locations"])


def test_eight_digit_coordinates_and_closed_codes_preserved(tmp_path):
    text = (f"error[E0308]: private\n --> {BINDING}:99999999:99999999\n"
            f" --> {BINDING}:100000000:2\n --> {BINDING}:-1:2\n"
            f"error[E12345]: private\n --> {CORE}:4:4\n")
    assert project(tmp_path, text) == [{"kind": "rustc", "code": "E0308", "locations": [loc(BINDING, 99999999, 99999999)]}]


def test_cargo_summary_and_json_strings_grant_no_fabricated_code_or_location(tmp_path):
    text = (f"error[E0277]: private\n --> {BINDING}:12:7\n"
            "error: could not compile private-package\n"
            f" --> {CORE}:22:7\n" + json.dumps({"message": "error[E0308]: private", "file_name": CORE}) + "\n")
    assert project(tmp_path, text) == [{"kind": "rustc", "code": "E0277", "locations": [loc(BINDING, 12)]}]


def test_log_tail_does_not_associate_orphaned_spans_without_held_header(tmp_path):
    text = "error[E0277]: private\n" + "x" * 65536 + f"\n --> {BINDING}:12:7\n"
    assert project(tmp_path, text) == []
