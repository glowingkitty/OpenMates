#!/usr/bin/env python3
"""Cross-framework Specification test-metadata parsing and validation fixtures.

The fixtures are synthetic and contain no product data. They establish one
framework-neutral comment format without changing test-runner behavior.
Architecture: docs/plans/contract-driven-development/plan.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "specifications.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_specification_metadata", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def registry() -> dict:
    return {
        "assertions": {
            "web-search.request.validated": {"specification": "feature.web-search@1", "fingerprint": "one"},
            "web-search.surface-parity": {"specification": "feature.web-search@1", "fingerprint": "two"},
        }
    }


# contract-test: tooling
def test_parses_python_typescript_and_swift_metadata(tmp_path):
    module = load_module()
    fixtures = {
        "test_api.py": """# contract-test: direct surface=rest_api assertions=web-search.request.validated\ndef test_rejects_blank_query():\n    pass\n""",
        "web.spec.ts": """// contract-test: supporting surface=gui.web assertions=web-search.surface-parity\ntest('shows results', async () => {});\n""",
        "SearchTests.swift": """// contract-test: direct surface=gui.apple assertions=web-search.surface-parity\nfunc testSearchResults() throws {}\n""",
    }

    parsed = []
    for name, content in fixtures.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        parsed.extend(module.parse_test_metadata(path))

    assert [record.classification for record in parsed] == ["direct", "supporting", "direct"]
    assert [record.surface for record in parsed] == ["rest_api", "gui.web", "gui.apple"]


# contract-test: tooling
def test_parses_multiline_parameterized_concurrent_and_tsx_tests(tmp_path):
    module = load_module()
    path = tmp_path / "web.spec.tsx"
    path.write_text(
        """// contract-test: direct surface=gui.web assertions=web-search.surface-parity
test.concurrent.each([
  ['one'],
])(
  'renders %s',
  async () => {},
);
// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
it(
  'renders multiline',
  async () => {},
);
""",
        encoding="utf-8",
    )

    records = module.parse_test_metadata(path)

    assert [record.name for record in records] == ["renders %s", "renders multiline"]
    assert [record.classification for record in records] == ["direct", "supporting"]


# contract-test: tooling
def test_mixed_file_parses_parameterized_title_after_large_table(tmp_path):
    module = load_module()
    rows = "\n".join(f"  ['row-{index}']," for index in range(20))
    path = tmp_path / "large.spec.ts"
    path.write_text(
        "// contract-test: tooling\ntest('ordinary', () => {});\n"
        "// contract-test: direct surface=gui.web assertions=web-search.surface-parity\n"
        f"test.each([\n{rows}\n])(\n  'large %s',\n  async () => {{}},\n);\n",
        encoding="utf-8",
    )

    records = module.parse_test_metadata(path)

    assert [record.name for record in records] == ["ordinary", "large %s"]
    assert records[1].assertions == ("web-search.surface-parity",)


# contract-test: tooling
def test_changed_behavioral_test_rejects_missing_metadata(tmp_path):
    module = load_module()
    path = tmp_path / "missing.spec.ts"
    path.write_text("test('unmapped behavior', async () => {});\n", encoding="utf-8")

    errors = module.check_test_file(path, registry(), changed=True)

    assert any("missing contract-test metadata" in error for error in errors)


# contract-test: tooling
def test_changed_test_file_with_no_recognized_cases_requires_file_classification(tmp_path):
    module = load_module()
    path = tmp_path / "custom.test.tsx"
    path.write_text("customRunner('behavior', () => {});\n", encoding="utf-8")

    errors = module.check_test_file(path, registry(), changed=True)

    assert any("no recognized test cases" in error for error in errors)


# contract-test: tooling
def test_direct_proof_rejects_unknown_assertion_and_missing_surface(tmp_path):
    module = load_module()
    path = tmp_path / "bad.py"
    path.write_text(
        "# contract-test: direct assertions=unknown.assertion\ndef test_unknown():\n    pass\n",
        encoding="utf-8",
    )

    errors = module.check_test_file(path, registry(), changed=True)

    assert any("surface" in error for error in errors)
    assert any("unknown assertion" in error for error in errors)


# contract-test: tooling
def test_infrastructure_classification_needs_no_product_assertion(tmp_path):
    module = load_module()
    path = tmp_path / "test_runner.py"
    path.write_text(
        "# contract-test: infrastructure\ndef test_fixture_loader():\n    pass\n",
        encoding="utf-8",
    )

    assert module.check_test_file(path, registry(), changed=True) == []


# contract-test: tooling
def test_legacy_unmapped_is_reported_but_only_blocks_when_changed(tmp_path):
    module = load_module()
    path = tmp_path / "legacy.test.ts"
    path.write_text(
        "// contract-test: legacy_unmapped\ntest('legacy behavior', () => {});\n",
        encoding="utf-8",
    )

    assert module.check_test_file(path, registry(), changed=False) == []
    assert any("legacy_unmapped" in error for error in module.check_test_file(path, registry(), changed=True))


# contract-test: tooling
def test_test_index_separates_direct_and_supporting_proof(tmp_path):
    module = load_module()
    direct = tmp_path / "direct.py"
    supporting = tmp_path / "supporting.test.ts"
    direct.write_text(
        "# contract-test: direct surface=rest_api assertions=web-search.request.validated\ndef test_request():\n    pass\n",
        encoding="utf-8",
    )
    supporting.write_text(
        "// contract-test: supporting surface=gui.web assertions=web-search.request.validated\ntest('render', () => {});\n",
        encoding="utf-8",
    )

    index = module.build_test_index([direct, supporting], registry())
    record = index["assertions"]["web-search.request.validated"]

    assert len(record["direct_tests"]) == 1
    assert len(record["supporting_tests"]) == 1
