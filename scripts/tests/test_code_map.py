"""Tests for scripts/code_map.py."""
# contract-test-file: tooling

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "code_map.py"


def cm(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True,
                          capture_output=True, check=False)


def test_outline_languages(tmp_path):
    (tmp_path / "a.py").write_text("class A:\n    def m(self):\n        pass\n\nasync def g():\n    pass\n")
    (tmp_path / "b.rs").write_text("pub struct S;\nimpl S {\n    pub fn go(&self) {}\n}\nenum E {}\n")
    (tmp_path / "c.ts").write_text("export function h() {}\nexport interface I {}\nexport const k = 1;\n")
    (tmp_path / "d.swift").write_text("struct V {\n    func body() {}\n}\nextension V {}\n")
    (tmp_path / "e.sh").write_text("foo() {\n  true\n}\n")
    (tmp_path / "f.svelte").write_text("<script lang=\"ts\">\n  function x() {}\n</script>\n<div>function y</div>\n")
    expect = {"a.py": ["3 lines" if False else "class A", "  def m", "async def g"],
              "b.rs": ["struct S", "impl S", "fn go", "enum E"],
              "c.ts": ["function h", "interface I", "export k"],
              "d.swift": ["struct V", "func body", "extension V"],
              "e.sh": ["function foo"], "f.svelte": ["function x"]}
    for name, parts in expect.items():
        out = cm("outline", str(tmp_path / name)).stdout
        for part in parts:
            assert part in out, (name, out)
    assert "function y" not in cm("outline", str(tmp_path / "f.svelte")).stdout


def test_outline_capped(tmp_path):
    (tmp_path / "big.py").write_text("".join(f"def f{i}():\n    pass\n" for i in range(300)))
    out = cm("outline", str(tmp_path / "big.py")).stdout
    assert len(out.splitlines()) <= 121
    assert "... " in out and "more" in out


def test_dir_map_skips_and_caps(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function x() {}\n")
    (tmp_path / "m.py").write_text('"""Module doc."""\ndef one():\n    pass\n')
    out = cm("dir", str(tmp_path)).stdout
    assert "m.py (3) Module doc. | one" in out
    assert "node_modules" not in out
    for i in range(250):
        (tmp_path / f"f{i}.py").write_text("x = 1\n")
    out = cm("dir", str(tmp_path)).stdout
    assert len(out.splitlines()) <= 200
    assert "narrow the path" in out
