import json

from backend.apps.code.application_identity import (
    derive_application_identity,
    humanise_package_name,
)


def _manifest(name, deps=None, dev=None):
    return json.dumps({"name": name, "dependencies": deps or {}, "devDependencies": dev or {}})


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_humanise_package_name():
    assert humanise_package_name("recipe-manager") == "Recipe Manager"
    assert humanise_package_name("@scope/recipe_manager.app") == "Recipe Manager App"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_react_vite_manifest_gives_name_and_framework():
    content = _manifest("recipe-manager", {"react": "^18"}, {"vite": "^5"})
    assert derive_application_identity(package_json_content=content) == ("Recipe Manager", "react")


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_vue_svelte_next_detection():
    assert derive_application_identity(package_json_content=_manifest("a-b", {"vue": "3"}))[1] == "vue"
    assert derive_application_identity(package_json_content=_manifest("a-b", dev={"svelte": "5"}))[1] == "svelte"
    assert derive_application_identity(package_json_content=_manifest("a-b", {"next": "14", "react": "18"}))[1] == "next"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_vite_only_manifest():
    assert derive_application_identity(package_json_content=_manifest("tool", dev={"vite": "5"}))[1] == "vite"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_model_given_name_wins():
    name, _ = derive_application_identity(given_name="Pantry Planner", package_json_content=_manifest("x-y"))
    assert name == "Pantry Planner"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_generic_package_name_loses_to_project_name():
    content = _manifest("vite-project", {"react": "18"})
    name, framework = derive_application_identity(package_json_content=content, project_name="Recipe Manager")
    assert (name, framework) == ("Recipe Manager", "react")


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_project_name_used_without_manifest_name():
    assert derive_application_identity(package_json_content="{}", project_name="Kitchen")[0] == "Kitchen"


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_invalid_manifest_falls_back_to_extensions_and_default_text():
    assert derive_application_identity(package_json_content="{oops", paths=["src/App.vue"]) == (
        "Generated application",
        "vue",
    )
    assert derive_application_identity() == ("Generated application", "web")


# contract-test: supporting surface=rest_api assertions=projects.creation.assistant-inferred
def test_fallback_placeholders_are_replaced():
    name, framework = derive_application_identity(
        given_name="Generated application",
        given_framework="web",
        package_json_content=_manifest("recipe-manager", {"react": "18"}),
    )
    assert (name, framework) == ("Recipe Manager", "react")
