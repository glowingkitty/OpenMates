"""Generated authored identity metadata agrees with backend contracts and declarations.

This engineering test executes the real generator and generated TypeScript. It
requires the UI's installed Node dependencies, but no browser, account or network.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "frontend/packages/ui/scripts/generate-embed-registry.js"
GENERATED = ROOT / "frontend/packages/ui/src/data/embedRegistry.generated.ts"


def node_json(source: str, value: object | None = None) -> object:
    """Execute a bounded account-free Node assertion and decode its result."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        input=json.dumps(value), capture_output=True, text=True, cwd=ROOT,
        check=True, timeout=30,
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def generated_registry() -> dict:
    """Exercise real generation and runtime immutability instead of TS formatting."""
    subprocess.run(
        ["node", str(GENERATOR)], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=30,
    )
    return node_json(f"""
        import {{ readFileSync }} from 'node:fs';
        import {{ createRequire }} from 'node:module';
        const require = createRequire({json.dumps(GENERATOR.as_uri())});
        const ts = require('typescript');
        const source = readFileSync({json.dumps(str(GENERATED))}, 'utf8');
        const result = ts.transpileModule(source, {{
            compilerOptions: {{ module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }},
            reportDiagnostics: true,
        }});
        if (result.diagnostics.length) throw new Error('Invalid generated TypeScript');
        const module = await import('data:text/javascript;base64,' + Buffer.from(result.outputText).toString('base64'));
        const mapping = module.AUTHORED_RESULT_KIND_MAP;
        let rejected = false;
        try {{ mapping['events.event'].appId = 'changed'; }} catch {{ rejected = true; }}
        console.log(JSON.stringify({{
            mapping, frozen: Object.isFrozen(mapping),
            entriesFrozen: Object.values(mapping).every(Object.isFrozen), rejected,
        }}));
    """)


def test_generated_kind_identities_agree_with_catalog_and_explicit_app_admissions(generated_registry):
    catalog = json.loads((ROOT / "shared/config/authored_result_types.json").read_text())["kinds"]
    actual = generated_registry["mapping"]
    declarations = {}
    for app_path in (ROOT / "backend/apps").glob("*/app.yml"):
        app = yaml.safe_load(app_path.read_text())
        for definition in app.get("embed_types", []):
            if definition.get("default_enabled") is False or not definition.get("authoring"):
                continue
            kind = definition["authoring"]["kind"]
            assert kind not in declarations
            declarations[kind] = (app_path.parent.name, definition)
    assert set(actual) == set(catalog) == set(declarations)
    assert len(actual) == 25
    for kind, expected in catalog.items():
        identity = actual[kind]
        app_id, declaration = declarations[kind]
        composite = declaration.get("has_children") is True
        assert identity["appId"] == expected["app_id"] == app_id
        assert identity["backendType"] == expected["backend_type"]
        assert identity["registrationId"] == declaration["id"]
        assert identity["skillId"] == declaration.get("skill_id")
        if identity["skillId"] is not None:
            assert identity["skillId"] == expected["skill_id"]
        frontend = declaration.get("child_frontend_type" if composite else "frontend_type") or None
        assert identity["frontendType"] == frontend
        if composite:
            assert identity["backendType"] == declaration["child_type"]
            assert identity["backendType"] != "app_skill_use"
    assert actual["tv.movie"]["frontendType"] is None
    assert actual["tv.series"]["frontendType"] is None
    assert all(identity["frontendType"] for kind, identity in actual.items() if not kind.startswith("tv."))


def test_generated_metadata_is_immutable_at_runtime(generated_registry):
    assert generated_registry["frozen"]
    assert generated_registry["entriesFrozen"]
    assert generated_registry["rejected"]
    assert generated_registry["mapping"]["events.event"]["appId"] == "events"


DIRECT = {
    "id": "movie", "app_id": "tv", "category": "direct", "backend_type": "tv_movie",
    "frontend_type": "", "authoring": {"kind": "tv.movie", "schema_id": "tv.movie"},
}
COMPOSITE = {
    "id": "search", "app_id": "events", "category": "app-skill-use", "skill_id": "search",
    "backend_type": "app_skill_use", "frontend_type": "app-skill-use", "has_children": True,
    "child_type": "event", "child_frontend_type": "events-event",
    "authoring": {"kind": "events.event", "schema_id": "events.event"},
}


def build(declarations: list[dict]) -> dict:
    return node_json(f"""
        import {{ readFileSync }} from 'node:fs';
        import {{ buildAuthoredResultKindMap }} from {json.dumps(GENERATOR.as_uri())};
        try {{
            const mapping = buildAuthoredResultKindMap(JSON.parse(readFileSync(0, 'utf8')));
            console.log(JSON.stringify({{ mapping }}));
        }} catch (error) {{
            console.log(JSON.stringify({{ error: error.message }}));
        }}
    """, declarations)


def test_direct_registration_id_never_invents_backend_skill_identity():
    direct = copy.deepcopy(DIRECT)
    result = build([direct, COMPOSITE])["mapping"]
    assert result["tv.movie"] == {
        "appId": "tv", "registrationId": "movie", "skillId": None,
        "backendType": "tv_movie", "frontendType": None,
    }
    assert result["events.event"]["skillId"] == "search"
    assert result["events.event"]["backendType"] == "event"
    assert result["events.event"]["frontendType"] == "events-event"
    direct["skill_id"] = "declared_skill"
    assert build([direct])["mapping"]["tv.movie"]["skillId"] == "declared_skill"


@pytest.mark.parametrize("template,patch", [
    (DIRECT, {"app_id": "other"}),
    (DIRECT, {"id": "other"}),
    (DIRECT, {"backend_type": ""}),
    (DIRECT, {"backend_type": "tv_movie\n"}),
    (DIRECT, {"frontend_type": " tv-movie "}),
    (DIRECT, {"skill_id": ""}),
    (DIRECT, {"authoring": {"kind": "tv.movie", "schema_id": "tv.series"}}),
    (DIRECT, {"authoring": {"kind": "movie", "schema_id": "movie"}}),
    (DIRECT, {"authoring": {"kind": "tv.movie", "schema_id": "tv.movie", "raw": True}}),
    (COMPOSITE, {"child_type": ""}),
    (COMPOSITE, {"has_children": False}),
    (COMPOSITE, {"skill_id": None}),
    (COMPOSITE, {"authoring": {"kind": "events.search", "schema_id": "events.search"}}),
])
def test_invalid_or_mismatched_admitted_identities_fail_generation(template, patch):
    definition = copy.deepcopy(template)
    definition.update(patch)
    assert "error" in build([definition])


def test_duplicate_canonical_identity_fails_even_when_values_are_identical():
    result = build([DIRECT, copy.deepcopy(DIRECT)])
    assert result["error"] == "Duplicate authored result kind tv.movie"
