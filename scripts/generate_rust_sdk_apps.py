#!/usr/bin/env python3
"""Generate reviewed Rust SDK App namespaces from the canonical SDK metadata loader.

Retired skills are removed from every SDK (no deprecated stubs are generated).
"""

from __future__ import annotations
import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages/openmates-rust/src/generated.rs"
METADATA = ROOT / "packages/openmates-rust/src/generated/metadata.json"
KEYWORDS = {
    "as",
    "async",
    "await",
    "break",
    "const",
    "continue",
    "crate",
    "dyn",
    "else",
    "enum",
    "extern",
    "false",
    "fn",
    "for",
    "if",
    "impl",
    "in",
    "let",
    "loop",
    "match",
    "mod",
    "move",
    "mut",
    "pub",
    "ref",
    "return",
    "self",
    "Self",
    "static",
    "struct",
    "super",
    "trait",
    "true",
    "type",
    "union",
    "unsafe",
    "use",
    "where",
    "while",
    "yield",
    "try",
}


def ident(value: str) -> str:
    return f"r#{value}" if value in KEYWORDS else value


def outputs() -> dict[Path, str]:
    spec = importlib.util.spec_from_file_location(
        "canonical_sdk_generator", ROOT / "scripts/generate_sdk_app_skills.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    skills = module.load_skills()
    grouped = {}
    for skill in skills:
        grouped.setdefault(skill["app_namespace_py"], []).append(skill)
    lines = [
        "//! Generated reviewed App namespaces. Regenerate with scripts/generate_rust_sdk_apps.py.",
        "use crate::{sdk::OpenMates, error::Result};",
        "use serde_json::Value;",
        "/// Reviewed public metadata embedded at build time; no runtime filesystem access.",
        'pub fn app_skill_metadata() -> Value { serde_json::from_str(include_str!("generated/metadata.json")).expect("generated SDK metadata") }',
        "#[derive(Clone, Copy)]",
        "pub struct AppSkills<'a> { sdk: &'a OpenMates }",
        "impl<'a> AppSkills<'a> {",
        "    pub(crate) fn new(sdk: &'a OpenMates) -> Self { Self { sdk } }",
    ]
    for namespace, entries in grouped.items():
        name = "".join(part.title() for part in namespace.split("_")) + "Skills"
        lines.append(
            f"    pub fn {ident(namespace)}(&self) -> {name}<'a> {{ {name} {{ sdk: self.sdk }} }}"
        )
    lines.append("}")
    for namespace, entries in grouped.items():
        name = "".join(part.title() for part in namespace.split("_")) + "Skills"
        lines.extend(
            [
                "#[derive(Clone, Copy)]",
                f"pub struct {name}<'a> {{ sdk: &'a OpenMates }}",
                f"impl {name}<'_> {{",
            ]
        )
        for entry in entries:
            method = ident(entry["skill_method_py"])
            app = json.dumps(entry["app_id"])
            skill = json.dumps(entry["skill_id"])
            lines.extend(
                [
                    f"    pub async fn {method}(&self, input: Value) -> Result<Value> {{",
                    f"        self.sdk.run_skill({app}, {skill}, input).await",
                    "    }",
                ]
            )
        lines.append("}")
    source = subprocess.run(
        ["rustfmt", "--edition", "2024", "--emit", "stdout"],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return {
        TARGET: source,
        METADATA: json.dumps(skills, ensure_ascii=False, indent=2) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in outputs().items():
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise SystemExit(
                    f"Generated Rust SDK output is stale: {path.relative_to(ROOT)}"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
