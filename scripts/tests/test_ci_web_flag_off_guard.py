"""Engineering test: the flag-off web build guard derives markers from source and flags leaks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_web_flag_off_guard as guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


# contract-test: infrastructure
def test_markers_are_derived_from_shared_worker_protocol():
    markers = guard.derive_markers(ROOT)
    assert {"unit_unavailable", "openmates:rust:"} <= markers
    assert "embedData" not in markers  # ordinary identifier on its own
    assert {"embedData", "embedWrite", "chatState"} <= guard.derive_namespaces(ROOT)


# contract-test: infrastructure
def test_scan_flags_wasm_marker_and_chunk_name(tmp_path):
    (tmp_path / "a.wasm").write_bytes(b"\0asm__wbindgen_placeholder__")
    (tmp_path / "ort.wasm").write_bytes(b"\0asm")
    (tmp_path / "worker.entry-abc.js").write_text("x")
    (tmp_path / "app.js").write_text("fail('install_failed')")
    (tmp_path / "ns.js").write_text("['embedData','embedWrite']")
    out = "\n".join(guard.scan(tmp_path, {"install_failed"}, {"worker.entry"}, frozenset({"embedData", "embedWrite"})))
    assert "a.wasm: wasm file" in out
    assert "ort.wasm" not in out
    assert "worker.entry-abc.js" in out
    assert "app.js: markers ['install_failed']" in out
    assert "ns.js: markers [\"all shared-worker namespaces" in out


# contract-test: infrastructure
def test_scan_passes_clean_build(tmp_path):
    (tmp_path / "app.js").write_text("console.log(1)")
    assert guard.scan(tmp_path, {"embedWrite"}, {"worker.entry"}) == []


# contract-test: infrastructure
def test_scan_ignores_generated_documentation_pages(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "status.html").write_text("unit_unavailable")
    (tmp_path / "app.js").write_text("fail('unit_unavailable')")
    out = "\n".join(guard.scan(tmp_path, {"unit_unavailable"}, set()))
    assert "docs/status.html" not in out
    assert "app.js: markers" in out
