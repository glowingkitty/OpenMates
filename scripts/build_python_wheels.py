#!/usr/bin/env python3
"""Build platform wheels of the Python SDK with the PyO3 core (prepare only).

The canonical `packages/openmates-python/pyproject.toml` stays a pure setuptools
project so `pip install -e packages/openmates-python` keeps working in CI without
a Rust toolchain. This tool assembles a temporary maturin project from exactly
that metadata (name, version, dependencies, URLs: no second copy to drift) plus
the package sources, and builds one abi3 (CPython >= 3.10) wheel for one target:

    python3 scripts/build_python_wheels.py --out dist/wheels                     # host
    python3 scripts/build_python_wheels.py --out dist/wheels --target x86_64-unknown-linux-gnu \\
        --compatibility manylinux_2_28                                           # in a manylinux image
    python3 scripts/build_python_wheels.py --out dist/wheels --target aarch64-apple-darwin
    python3 scripts/build_python_wheels.py --assemble-only .wheel-build/openmates   # for maturin-action

Supported release targets: x86_64/aarch64 Linux (manylinux) and x86_64/aarch64
macOS. Windows is explicitly out of scope. Nothing is uploaded or published.
Each built wheel is checked to contain the native extension and the package.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/openmates-python"
CRATE = ROOT / "packages/openmates-session-bindings/Cargo.toml"
TARGETS = {
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
}


def toml_value(value) -> str:
    """Minimal TOML for the copied [project] table (strings, lists, tables)."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def maturin_pyproject(project: dict) -> str:
    lines = ['[build-system]', 'requires = ["maturin>=1.9,<2"]', 'build-backend = "maturin"', "", "[project]"]
    tables = {}
    for key, value in project.items():
        if isinstance(value, dict) and key == "urls":
            tables[key] = value
        else:
            lines.append(f"{key} = {toml_value(value)}")
    for key, value in tables.items():
        lines += ["", f"[project.{key}]"] + [f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()]
    lines += [
        "",
        "[tool.maturin]",
        f"manifest-path = {json.dumps(str(CRATE))}",
        'module-name = "openmates._native"',
        'python-source = "."',
        'features = ["python-bindings"]',
        'bindings = "pyo3"',
        "locked = true",
        "",
    ]
    return "\n".join(lines)


def assemble(directory: Path) -> None:
    project = tomllib.loads((PACKAGE / "pyproject.toml").read_text())["project"]
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "_native*.so", "_native*.pyd", "_native*.dylib")
    shutil.copytree(PACKAGE / "openmates", directory / "openmates", ignore=ignore)
    for name in ("README.md", "LICENSE"):
        if (PACKAGE / name).is_file():
            shutil.copy2(PACKAGE / name, directory / name)
    (directory / "pyproject.toml").write_text(maturin_pyproject(project))


def verify(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        tags = [line for line in archive.read(next(n for n in names if n.endswith(".dist-info/WHEEL"))).decode().splitlines()
                if line.startswith("Tag:")]
    native = [name for name in names if name.startswith("openmates/_native.") and name.endswith((".so", ".pyd"))]
    if len(native) != 1 or "openmates/session_client.py" not in names or "openmates/sdk.py" not in names:
        raise SystemExit(f"{wheel.name}: wheel is missing the native extension or SDK sources")
    if not tags or not all("-abi3-" in tag for tag in tags):
        raise SystemExit(f"{wheel.name}: expected one abi3 (cp310+) wheel, got {tags}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="Wheel output directory (required unless --assemble-only).")
    parser.add_argument("--assemble-only", type=Path, metavar="DIR",
                        help="Only write the maturin project into DIR (for maturin-action in CI); build nothing.")
    parser.add_argument("--target", choices=sorted(TARGETS), help="Rust target triple; default: host")
    parser.add_argument("--compatibility", default=None,
                        help="maturin --compatibility (e.g. manylinux_2_28 inside a manylinux image; 'linux' for a local host check)")
    parser.add_argument("--debug", action="store_true", help="Build the dev profile (local checks only).")
    args = parser.parse_args()
    if args.assemble_only:
        target = args.assemble_only.resolve()
        if target.exists():
            raise SystemExit(f"{target} already exists")
        target.mkdir(parents=True)
        assemble(target)
        print(f"Assembled maturin project: {target}")
        return 0
    if args.out is None:
        parser.error("--out is required unless --assemble-only is given")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    before = set(out.glob("*.whl"))
    with tempfile.TemporaryDirectory(prefix="openmates-wheel-") as temporary:
        project = Path(temporary)
        assemble(project)
        command = [sys.executable, "-m", "maturin", "build", "--locked", "--out", str(out)]
        command += ["--profile", "dev"] if args.debug else ["--release"]
        if args.target:
            command += ["--target", args.target]
        if args.compatibility:
            command += ["--compatibility", args.compatibility]
        subprocess.run(command, cwd=project, check=True)
    built = sorted(set(out.glob("*.whl")) - before)
    if len(built) != 1:
        raise SystemExit(f"expected exactly one new wheel, found {len(built)}")
    verify(built[0])
    print(f"Built wheel: {built[0]}")
    return 0


def verify_main() -> int:
    """`python3 scripts/build_python_wheels.py --verify WHEEL...` checks built wheels."""
    for name in sys.argv[2:]:
        verify(Path(name))
        print(f"verified {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify_main() if sys.argv[1:2] == ["--verify"] else main())
