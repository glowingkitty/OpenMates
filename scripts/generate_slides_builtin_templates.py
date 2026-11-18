#!/usr/bin/env python3
"""Generate the web copy of the built-in slides templates.

Reads ``backend/apps/slides/templates/<id>.slides`` (plain first, then by id) and
writes ``slidesBuiltinTemplates.generated.ts``. ``--check`` exits 1 when the
generated file is stale. Format: docs/architecture/apps/slides-format.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "backend" / "apps" / "slides" / "templates"
OUTPUT = (
    ROOT / "frontend" / "packages" / "ui" / "src" / "components" / "embeds" / "slides"
    / "slidesBuiltinTemplates.generated.ts"
)
_TITLE_RE = re.compile(r'<deck\b[^>]*\stitle="([^"]*)"')


def render() -> str:
    entries = []
    for path in sorted(TEMPLATES_DIR.glob("*.slides"), key=lambda p: (p.stem != "plain", p.stem)):
        markup = path.read_text(encoding="utf-8")
        match = _TITLE_RE.search(markup)
        if not match:
            raise SystemExit(f"{path}: deck title missing")
        entries.append((f"builtin:{path.stem}", match.group(1), markup))
    body = "".join(
        f"  {{\n    id: {json.dumps(i)},\n    name: {json.dumps(n, ensure_ascii=False)},\n"
        f"    markup: {json.dumps(m, ensure_ascii=False)},\n  }},\n"
        for i, n, m in entries
    )
    return (
        "// GENERATED FILE - do not edit. Run scripts/generate_slides_builtin_templates.py.\n"
        "// Source: backend/apps/slides/templates/*.slides (docs/architecture/apps/slides-format.md).\n\n"
        "export interface BuiltinSlidesTemplate {\n  id: string;\n  name: string;\n  markup: string;\n}\n\n"
        f"export const BUILTIN_SLIDES_TEMPLATES: readonly BuiltinSlidesTemplate[] = [\n{body}];\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when the generated file is stale")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"stale: {OUTPUT.relative_to(ROOT)}; run scripts/generate_slides_builtin_templates.py")
            return 1
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
