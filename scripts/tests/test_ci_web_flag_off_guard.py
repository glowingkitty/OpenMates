"""Engineering test: the flag-off web build guard derives markers from source and flags leaks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_web_flag_off_guard as guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


# contract-test: infrastructure
def test_markers_are_derived_from_shared_worker_protocol():
    markers = guard.derive_markers(ROOT)
    assert {"embedData", "embedWrite", "chatState", "unit_unavailable", "openmates:rust:"} <= markers
    assert "core" not in markers and "ws" not in markers


# contract-test: infrastructure
def test_scan_flags_wasm_marker_and_chunk_name(tmp_path):
    (tmp_path / "a.wasm").write_bytes(b"\0asm")
    (tmp_path / "worker.entry-abc.js").write_text("x")
    (tmp_path / "app.js").write_text("send('embedWrite')")
    out = "\n".join(guard.scan(tmp_path, {"embedWrite"}, {"worker.entry"}))
    assert "a.wasm: wasm file" in out
    assert "worker.entry-abc.js" in out
    assert "app.js: markers ['embedWrite']" in out


# contract-test: infrastructure
def test_scan_passes_clean_build(tmp_path):
    (tmp_path / "app.js").write_text("console.log(1)")
    assert guard.scan(tmp_path, {"embedWrite"}, {"worker.entry"}) == []
