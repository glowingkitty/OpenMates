"""Derive a display name and framework for a generated application embed.

Pure helpers: no I/O. The name prefers the model-given name, then the `name`
of the app's package.json (humanised), then the Project name; the framework is
detected from package.json dependencies, then from file extensions.
"""

import json
import re
from typing import Any, Mapping, Optional, Sequence

FALLBACK_APPLICATION_NAME = "Generated application"
FALLBACK_APPLICATION_FRAMEWORK = "web"

# Ordered: the first match wins, so meta-frameworks precede their base library.
_FRAMEWORK_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("next", "next"),
    ("nuxt", "nuxt"),
    ("@sveltejs/kit", "sveltekit"),
    ("astro", "astro"),
    ("@remix-run/react", "remix"),
    ("react", "react"),
    ("vue", "vue"),
    ("svelte", "svelte"),
    ("solid-js", "solid"),
    ("@angular/core", "angular"),
    ("preact", "preact"),
    ("vite", "vite"),
)
_FRAMEWORK_EXTENSIONS: tuple[tuple[str, str], ...] = (
    (".svelte", "svelte"),
    (".vue", "vue"),
    (".jsx", "react"),
    (".tsx", "react"),
)
_GENERIC_NAMES = {"app", "application", "my-app", "web-app", "webapp", "vite-project", "project"}


def humanise_package_name(raw_name: str) -> str:
    """Turn `@scope/recipe-manager_app` into `Recipe Manager App`."""
    name = raw_name.strip().rsplit("/", 1)[-1]
    words = [word for word in re.split(r"[-_.\s]+", name) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def parse_package_json(content: Optional[str]) -> dict[str, Any]:
    """Return the parsed package.json object, or an empty dict when it is not valid JSON."""
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def detect_framework(package_json: Mapping[str, Any], paths: Sequence[str]) -> Optional[str]:
    """Detect the framework from manifest dependencies, else from file extensions."""
    dependencies: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = package_json.get(key)
        if isinstance(section, dict):
            dependencies.update(str(name) for name in section)
    for dependency, framework in _FRAMEWORK_DEPENDENCIES:
        if dependency in dependencies:
            return framework
    for extension, framework in _FRAMEWORK_EXTENSIONS:
        if any(path.endswith(extension) for path in paths):
            return framework
    return None


def derive_application_identity(
    *,
    given_name: Optional[str] = None,
    given_framework: Optional[str] = None,
    package_json_content: Optional[str] = None,
    project_name: Optional[str] = None,
    paths: Sequence[str] = (),
) -> tuple[str, str]:
    """Return `(name, framework)` for an application embed.

    The fallback texts are used only when nothing can be derived. A generic
    package name (for example `vite-project`) loses against the Project name.
    """
    manifest = parse_package_json(package_json_content)

    name = (given_name or "").strip()
    if not name or name == FALLBACK_APPLICATION_NAME:
        manifest_name = manifest.get("name")
        humanised = humanise_package_name(manifest_name) if isinstance(manifest_name, str) else ""
        project = (project_name or "").strip()
        if humanised and not (
            project and isinstance(manifest_name, str) and manifest_name.strip().lower() in _GENERIC_NAMES
        ):
            name = humanised
        else:
            name = project or humanised or FALLBACK_APPLICATION_NAME

    framework = (given_framework or "").strip()
    if not framework or framework == FALLBACK_APPLICATION_FRAMEWORK:
        framework = detect_framework(manifest, paths) or FALLBACK_APPLICATION_FRAMEWORK
    return name, framework
