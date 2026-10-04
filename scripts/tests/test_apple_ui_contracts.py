"""Focused tests for Apple web-contract source coverage.

The contract audit must scan canonical component files rather than forcing
accessibility identifiers into unrelated views. These tests use repository
paths only and do not access private runtime or simulator data.
"""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import apple_ui_contracts

APP_SKILL_ENTRY = "if embed.isAppSkillUse { AppSkillUseRenderer(embed: embed, mode: mode) }\n"


# contract-test: tooling
def test_message_input_audit_scans_canonical_composer_component() -> None:
    paths = apple_ui_contracts.swift_files_for_message_input()

    assert any(path.name == "MessageComposerView.swift" for path in paths)
    assert any(path.name == "ComposerAttachmentActionRow.swift" for path in paths)


# contract-test: tooling
def test_embed_showcase_apps_read_current_slug_registry() -> None:
    source = "export const EMBED_APP_SLUGS = ['code', 'web'] as const;"
    assert apple_ui_contracts._extract_showcase_apps(source) == {"code", "web"}


# contract-test: tooling
def test_attachment_icons_must_exist_in_web_source_assets() -> None:
    assert apple_ui_contracts.missing_attachment_icons(
        'Icon("add"); Icon("plus"); item("missing", label, "files", action)', {"plus"}
    ) == {"add", "missing"}


def _embed_contract() -> dict:
    return {
        "schemaVersion": 1,
        "surface": "embeds",
        "dimension": {"id": "iphone-light-ltr"},
        "apps": [{"appId": app} for app in sorted(apple_ui_contracts.REQUIRED_EMBED_SHOWCASE_APPS)],
        "surfaces": [
            {
                "key": "web:search:1",
                "appId": "web",
                "sources": {"preview": True, "fullscreen": True},
                "previews": [{"capture": {"visibleText": "Example"}}],
                "fullscreen": {"visibleText": "Example"},
            }
        ],
        "registrySurfaces": [
            {
                "registryKey": "example",
                "surface": surface,
                "exists": True,
                "renderError": False,
                "capture": {"visibleText": "Example", "computedStyle": {"width": "300px"}},
                "screenshotPath": f"iphone-light-ltr/registry/example-{surface}.png",
            }
            for surface in ("preview", "fullscreen")
        ],
    }


# contract-test: tooling
def test_embed_registry_contract_requires_each_rendered_surface(monkeypatch) -> None:
    monkeypatch.setattr(apple_ui_contracts, "_extract_ts_object_keys", lambda *_: {"example"})
    contract = _embed_contract()
    assert apple_ui_contracts.validate_embeds_contract(contract) == []

    missing = copy.deepcopy(contract)
    missing["registrySurfaces"].pop()
    assert any("missing 1 registry surfaces" in error for error in apple_ui_contracts.validate_embeds_contract(missing))

    duplicate = copy.deepcopy(contract)
    duplicate["registrySurfaces"].append(copy.deepcopy(duplicate["registrySurfaces"][0]))
    assert any("duplicate registry surface" in error for error in apple_ui_contracts.validate_embeds_contract(duplicate))


# contract-test: tooling
def test_embed_registry_contract_rejects_uncaptured_or_private_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(apple_ui_contracts, "_extract_ts_object_keys", lambda *_: {"example"})
    contract = _embed_contract()
    contract["registrySurfaces"][0]["capture"] = None
    contract["registrySurfaces"][1]["screenshotPath"] = "/Users/example/private.png"
    errors = apple_ui_contracts.validate_embeds_contract(contract)
    assert any("missing rendered capture" in error for error in errors)
    assert any("screenshot must be relative" in error for error in errors)


def _hosting_audit_sources(tmp_path: Path, monkeypatch):
    web, native = tmp_path / "web", tmp_path / "native"
    def write(root, relative, source):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return path
    registry = "\n".join(
        f'export const EMBED_{mode}_COMPONENTS: Record<string, string> = {{\n'
        '  "app:hosting:search_domains": "HostingSearch.svelte",\n'
        '  "hosting-domain": "HostingDomain.svelte",\n};'
        for mode in ("PREVIEW", "FULLSCREEN")
    )
    write(web, "frontend/packages/ui/src/data/embedRegistry.generated.ts", registry)
    write(web, "frontend/apps/web_app/src/lib/devPreviewEmbedApps.ts", "export const EMBED_APP_SLUGS = ['hosting'] as const;")
    write(web, "frontend/apps/web_app/src/routes/dev/preview/embeds/[app=embedApp]/+page.svelte", "EMBED_APP_SLUGS")
    models = write(native, "apple/OpenMates/Sources/Core/Models/EmbedModels.swift", '''enum EmbedType: String {
    case hostingSearch = "app:hosting:search_domains"
    case hostingDomain = "hosting-domain"
}
''')
    write(native, "apple/OpenMates/Sources/DevPreview/DevEmbedPreviewFixtures.swift", '''enum DevEmbedPreviewApp: String {
    case hosting
}
// Supplemental fixture provider is selected by the gallery switch.
case .hosting: return DevHostingEmbedFixtures.skills
''')
    # Hosting's literal records are in a supplemental file, with a chained
    # helper that derives the gallery ID from embed.type rather than skill(id:).
    write(native, "apple/OpenMates/Sources/DevPreview/DevHostingEmbedFixtures.swift", '''
func search() { let parent = record(id: "synthetic", type: "app:hosting:search_domains"); return skill(parent) }
func domain() { return record(id: "synthetic-domain", type: "hosting-domain") }
''')
    content = write(native, "apple/OpenMates/Sources/Features/Embeds/Views/EmbedContentView.swift", APP_SKILL_ENTRY + '''switch embedType {
case .hostingDomain: HostingDomainRenderer(data: data, mode: mode)
default: GenericEmbedRenderer(data: data, mode: mode)
}
''')
    parent = write(native, "apple/OpenMates/Sources/Features/Embeds/Renderers/AppSkillUseRenderer.swift", '''
private var preview: AnyView {
    if appId == "hosting", skillId == "search_domains" {
        return AnyView(HostingSearchRenderer(data: data, mode: .preview))
    } else { return AnyView(textSearchPreview) }
}
private var fullscreen: some View {
    if appId == "hosting", skillId == "search_domains" {
        HostingSearchRenderer(data: data, mode: .fullscreen)
    } else { SearchResultFullscreenRow(embed: child) }
}
''')
    monkeypatch.setattr(apple_ui_contracts, "REQUIRED_EMBED_SHOWCASE_APPS", {"hosting"})
    monkeypatch.setattr(apple_ui_contracts, "REQUIRED_APP_SPECIFIC_EMBED_IDENTIFIERS", set())
    return web, native, models, content, parent


# contract-test: tooling
def test_embed_audit_counts_supplemental_chained_fixtures_and_both_routes(tmp_path, monkeypatch):
    web, native, *_ = _hosting_audit_sources(tmp_path, monkeypatch)
    errors, warnings = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert errors == []
    assert any("2 web previews, 2 web fullscreens" in warning for warning in warnings)


# contract-test: tooling
def test_embed_audit_rejects_missing_hosting_enum(tmp_path, monkeypatch):
    web, native, models, *_ = _hosting_audit_sources(tmp_path, monkeypatch)
    models.write_text(models.read_text().replace('    case hostingDomain = "hosting-domain"\n', ""))
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert any("Apple EmbedType missing registry keys: hosting-domain" in error for error in errors)


# contract-test: tooling
def test_embed_audit_rejects_hosting_child_generic_even_with_fixture(tmp_path, monkeypatch):
    web, native, _, content, _ = _hosting_audit_sources(tmp_path, monkeypatch)
    content.write_text(content.read_text().replace("HostingDomainRenderer", "GenericEmbedRenderer"))
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert any("generic fallback (preview): hosting-domain" in error for error in errors)
    assert any("generic fallback (fullscreen): hosting-domain" in error for error in errors)


# contract-test: tooling
def test_embed_audit_rejects_hosting_child_default_fallback(tmp_path, monkeypatch):
    web, native, _, content, _ = _hosting_audit_sources(tmp_path, monkeypatch)
    content.write_text(APP_SKILL_ENTRY + 'switch embedType {\ndefault: GenericEmbedRenderer(data: data, mode: mode)\n}')
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert any("generic fallback (preview): hosting-domain" in error for error in errors)


# contract-test: tooling
def test_embed_audit_rejects_missing_parent_fullscreen_route(tmp_path, monkeypatch):
    web, native, _, _, parent = _hosting_audit_sources(tmp_path, monkeypatch)
    parent.write_text(parent.read_text().replace('HostingSearchRenderer(data: data, mode: .fullscreen)', 'Text("unavailable")'))
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert errors == ["missing concrete Apple embed route (fullscreen): app:hosting:search_domains"]


# contract-test: tooling
def test_shared_parent_is_review_warning_but_new_hosting_is_missing_route():
    parent = '''private var preview: AnyView {
        if appId == "other", skillId == "search" { OtherRenderer(mode: .preview) }
        else { return AnyView(textSearchPreview) }
    }
    private var fullscreen: some View {
        if appId == "other", skillId == "search" { OtherRenderer(mode: .fullscreen) }
        else { SearchResultFullscreenRow(embed: child) }
    }'''
    keys = {"app:mail:search", "app:hosting:search_domains"}
    errors, warnings = apple_ui_contracts._native_embed_dispatch(keys, {key: key for key in keys}, APP_SKILL_ENTRY, parent)
    assert len(errors) == 2 and all("app:hosting:search_domains" in error for error in errors)
    assert len(warnings) == 2 and all("shared AppSkillUseRenderer parent" in warning for warning in warnings)


# contract-test: tooling
def test_fixture_types_accept_typed_helpers_and_ignore_comments():
    types = apple_ui_contracts._fixture_registry_types('''
        // record(type: "missing")
        domainSearch(type: .healthSearch, childType: .healthAppointment)
        appSkill(type: EmbedType.electronicsSearch.rawValue)
        record(type: "hosting-domain", url: "https://example.test")
    ''', {"app:health:search_appointments": "healthSearch", "health-appointment": "healthAppointment", "app:electronics:search_components": "electronicsSearch"})
    assert types == {"app:health:search_appointments", "health-appointment", "app:electronics:search_components", "hosting-domain"}


# contract-test: tooling
def test_missing_registry_is_derived_read_only_with_generator_component_rules(tmp_path, monkeypatch):
    definitions = [
        {"category": "app-skill-use", "app_id": "hosting", "skill_id": "search_domains",
         "preview_component": "SearchPreview.svelte", "fullscreen_component": "SearchFullscreen.svelte",
         "has_children": True, "child_frontend_type": "hosting-domain",
         "child_preview_component": "DomainPreview.svelte", "child_fullscreen_component": "DomainFullscreen.svelte"},
        {"category": "direct", "frontend_type": "virtual", "preview_component": "Virtual.svelte", "fullscreen_component": "null"},
        {"category": "internal", "frontend_type": "ignored", "preview_component": "Ignored.svelte"},
    ]
    def reader(args, **kwargs):
        assert args[0] == "node"
        assert "default_enabled !== false" in args[2]
        assert "generate-embed-registry" not in args[2]
        return SimpleNamespace(stdout=json.dumps(definitions))
    monkeypatch.setattr(apple_ui_contracts.shutil, "which", lambda _: "node")
    monkeypatch.setattr(apple_ui_contracts.subprocess, "run", reader)
    source = apple_ui_contracts._embed_registry_source(tmp_path)
    assert apple_ui_contracts._extract_ts_object_keys(source, "EMBED_PREVIEW_COMPONENTS") == {"app:hosting:search_domains", "hosting-domain", "virtual"}
    assert apple_ui_contracts._extract_ts_object_keys(source, "EMBED_FULLSCREEN_COMPONENTS") == {"app:hosting:search_domains", "hosting-domain"}
    assert list(tmp_path.iterdir()) == []


# contract-test: tooling
def test_specialized_route_requires_live_mode_dispatch_and_case_body():
    parent = '''static func specializedKind(appId: String, skillId: String) -> SpecializedKind? {
        switch (appId, skillId) { case ("music", "generate"): return .musicGenerate
        default: return nil }
    }
    private var preview: AnyView {
        if let specialized = Self.specializedKind(appId: appId, skillId: skillId) {
            return specializedPreview(specialized)
        } else { return AnyView(textSearchPreview) }
    }
    private var fullscreen: some View {
        if let specialized = Self.specializedKind(appId: appId, skillId: skillId) {
            specializedFullscreen(specialized)
        } else { SearchResultFullscreenRow(embed: child) }
    }
    private func specializedPreview(_ kind: SpecializedKind) -> AnyView {
        switch kind {
        case .musicGenerate: return AnyView(MusicGenerateEmbedRenderer(mode: .preview))
        }
    }
    private func specializedFullscreen(_ kind: SpecializedKind) -> some View {
        switch kind {
        case .musicGenerate: MusicGenerateEmbedRenderer(mode: .fullscreen)
        }
    }'''
    keys = {"app:music:generate"}; cases = {"app:music:generate": "musicGenerate"}
    assert apple_ui_contracts._native_embed_dispatch(keys, cases, APP_SKILL_ENTRY, parent) == ([], [])
    disconnected = parent.replace("return specializedPreview(specialized)", 'Text("MusicGenerateEmbedRenderer(mode: .preview)")')
    errors, _ = apple_ui_contracts._native_embed_dispatch(keys, cases, APP_SKILL_ENTRY, disconnected)
    assert errors == ["missing concrete Apple embed route (preview): app:music:generate"]


def _hosting_predicate_entry(content, native):
    content.write_text('''var body: some View {
        VStack {
            if HostingEmbedKind.isSearch(embed) {
                HostingSearchEmbedRenderer(embed: embed, mode: mode)
            } else if HostingEmbedKind.isDomain(embed) {
                HostingDomainEmbedRenderer(embed: embed, mode: mode)
            } else if embed.isAppSkillUse {
                AppSkillUseRenderer(embed: embed, mode: mode)
            } else {
                switch embedType {
                default: GenericEmbedRenderer(data: data, mode: mode)
                }
            }
        }
    }''')
    helper = native / "apple/OpenMates/Sources/Features/Embeds/Renderers/HostingEmbedModel.swift"
    helper.write_text('''enum HostingEmbedKind {
        static func isSearch(_ embed: EmbedRecord) -> Bool {
            if embed.type == "app:hosting:search_domains" { return true }
            return embed.appId == "hosting" && embed.skillId == "search_domains" && embed.isAppSkillUse
        }
        static func isDomain(_ embed: EmbedRecord) -> Bool {
            ["hosting-domain", "hosting_domain"].contains(embed.type)
        }
    }''')
    return helper


# contract-test: tooling
def test_embed_audit_traces_supplemental_production_predicates(tmp_path, monkeypatch):
    web, native, _, content, parent = _hosting_audit_sources(tmp_path, monkeypatch)
    _hosting_predicate_entry(content, native)
    parent.write_text("")  # Real entry predicates precede the composite renderer.
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert errors == []


# contract-test: tooling
def test_predicate_route_calling_generic_still_fails(tmp_path, monkeypatch):
    web, native, _, content, _ = _hosting_audit_sources(tmp_path, monkeypatch)
    _hosting_predicate_entry(content, native)
    content.write_text(content.read_text().replace("HostingDomainEmbedRenderer", "GenericEmbedRenderer"))
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert any("generic fallback (preview): hosting-domain" in error for error in errors)
    assert any("generic fallback (fullscreen): hosting-domain" in error for error in errors)


# contract-test: tooling
def test_false_predicate_type_mention_is_not_registration(tmp_path, monkeypatch):
    web, native, _, content, parent = _hosting_audit_sources(tmp_path, monkeypatch)
    helper = _hosting_predicate_entry(content, native)
    parent.write_text("")
    helper.write_text(helper.read_text().replace('if embed.type == "app:hosting:search_domains" { return true }',
                                               'if embed.type == "app:hosting:search_domains" { return false }'))
    errors, _ = apple_ui_contracts.audit_embeds(web_root=web, native_root=native)
    assert any("missing concrete Apple embed route (preview): app:hosting:search_domains" in error for error in errors)
