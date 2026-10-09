"""Build immutable, commit-matched locale files outside the product checkout.

The caller must hold the admitted dev-stack Docker operation while preparing an
artifact. Selection is read-only and verifies every published locale file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


TRANSLATION_SERVICES = frozenset({
    "api", "task-worker", "workflow-worker", "task-scheduler",
    "core-worker", "reminder-worker", "user-init-worker", "user-tasks-worker",
    "app-ai-worker", "app-images-worker", "app-music-worker", "app-videos-worker",
    "app-pdf-worker", "app-docs-worker", "app-code-worker", "app-social-media-worker",
})
MANIFEST_NAME = "manifest.json"
OVERLAY_NAME = "docker-compose.translations.json"


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=checkout, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def source_commit(checkout: Path) -> str:
    """Reject checkout edits, including untracked files, before using HEAD."""
    if _git(checkout, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError(f"Product runtime checkout is dirty: {checkout}")
    commit = _git(checkout, "rev-parse", "HEAD")
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise RuntimeError("Product runtime checkout has no valid source commit")
    return commit


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _node24_executable() -> str:
    configured = os.environ.get("OPENMATES_NODE24_BIN")
    candidates = [Path(configured)] if configured else []
    candidates.extend(sorted((Path.home() / ".nvm/versions/node").glob("v24.*/bin/node"), reverse=True))
    found = shutil.which("node24") or shutil.which("node")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        try:
            result = subprocess.run([str(candidate), "--version"], capture_output=True, text=True)
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip().startswith("v24."):
            return str(candidate)
    raise RuntimeError("Node 24 is required to generate product runtime translations")


def _artifact_dir(store: Path, commit: str) -> Path:
    return store / commit


def _required_locale_files(checkout: Path) -> set[str]:
    try:
        languages = json.loads(
            (checkout / "frontend/packages/ui/src/i18n/languages.json").read_text(encoding="utf-8")
        )["languages"]
        names = {f"{language['code']}.json" for language in languages}
        if not names or any(name != Path(name).name for name in names):
            raise ValueError("invalid language code")
        return names
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read required product languages: {exc}") from exc


def _overlay_content(locales: Path) -> dict:
    mount = {"type": "bind", "source": str(locales), "target": "/translations", "read_only": True}
    return {"services": {service: {"volumes": [mount]} for service in sorted(TRANSLATION_SERVICES)}}


def _validate_locale_structure(value: object, path: str = "") -> None:
    if not isinstance(value, dict):
        raise ValueError(f"locale node is not an object: {path or '<root>'}")
    for key, child in value.items():
        child_path = f"{path}.{key}" if path else key
        if key == "text":
            if not isinstance(child, str):
                raise ValueError(f"locale text is not a string: {child_path}")
        else:
            _validate_locale_structure(child, child_path)


def _validate_artifact(artifact: Path, commit: str, expected_files: set[str]) -> Path:
    try:
        if artifact.is_symlink() or (artifact / "locales").is_symlink():
            raise ValueError("artifact contains a directory symlink")
        manifest = json.loads((artifact / MANIFEST_NAME).read_text(encoding="utf-8"))
        files = manifest["files"]
        if manifest["commit"] != commit or not isinstance(files, dict) or set(files) != expected_files:
            raise ValueError("manifest source identity or files are invalid")
        locales = artifact / "locales"
        if {path.name for path in locales.iterdir()} != set(files):
            raise ValueError("locale file set differs from manifest")
        for name, digest in files.items():
            if name != Path(name).name or not name.endswith(".json") or len(digest) != 64:
                raise ValueError("invalid locale manifest entry")
            locale = locales / name
            if not locale.is_file() or locale.is_symlink() or _sha256(locale) != digest:
                raise ValueError(f"locale hash mismatch: {name}")
            _validate_locale_structure(json.loads(locale.read_text(encoding="utf-8")))
        overlay = artifact / OVERLAY_NAME
        if (artifact / MANIFEST_NAME).is_symlink() or overlay.is_symlink():
            raise ValueError("artifact contains a metadata symlink")
        if json.loads(overlay.read_text(encoding="utf-8")) != _overlay_content(locales):
            raise ValueError("translation mount overlay is invalid")
        return overlay
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid product translation artifact {artifact}: {exc}") from exc


def selected_overlay(checkout: Path, store: Path) -> Path | None:
    """Select only a complete artifact for this clean checkout's exact HEAD."""
    commit = source_commit(checkout)
    artifact = _artifact_dir(store, commit)
    if not artifact.exists():
        return None
    return _validate_artifact(artifact, commit, _required_locale_files(checkout))


def prepare_artifact(checkout: Path, store: Path) -> Path:
    """Generate and validate in staging, then publish with one directory rename."""
    checkout = checkout.resolve()
    store = store.resolve()
    if store.is_relative_to(checkout):
        raise RuntimeError("Translation artifacts must be outside the product checkout")
    commit = source_commit(checkout)
    expected_files = _required_locale_files(checkout)
    existing = _artifact_dir(store, commit)
    if existing.exists():
        return _validate_artifact(existing, commit, expected_files)
    node = _node24_executable()
    store.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{commit}.", dir=store))
    try:
        ui = staging / "frontend" / "packages" / "ui"
        web = staging / "frontend" / "apps" / "web_app"
        shutil.copytree(checkout / "frontend/packages/ui/src", ui / "src")
        shutil.copytree(checkout / "frontend/apps/web_app/src", web / "src")
        scripts = ui / "scripts"
        scripts.mkdir()
        for name in ("build-translations.js", "validate-locales.js", "languages-config.js"):
            shutil.copy2(checkout / "frontend/packages/ui/scripts" / name, scripts / name)
        shutil.copy2(checkout / "frontend/packages/ui/package.json", ui / "package.json")
        (ui / "node_modules").symlink_to(checkout / "frontend/packages/ui/node_modules", target_is_directory=True)
        locales = ui / "src/i18n/locales"
        shutil.rmtree(locales, ignore_errors=True)
        for script in ("build-translations.js", "validate-locales.js"):
            result = subprocess.run([node, str(scripts / script)], cwd=ui, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"{script} failed: {(result.stderr or result.stdout)[-3000:]}")
        if source_commit(checkout) != commit:
            raise RuntimeError("Product runtime source changed while translations were generated")
        files = {path.name: _sha256(path) for path in sorted(locales.glob("*.json"))}
        if set(files) != expected_files:
            raise RuntimeError("Translation generator produced an incomplete locale file set")
        published_locales = existing / "locales"
        (staging / MANIFEST_NAME).write_text(
            json.dumps({"commit": commit, "files": files}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / OVERLAY_NAME).write_text(
            json.dumps(_overlay_content(published_locales), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        locales.rename(staging / "locales")
        shutil.rmtree(staging / "frontend")
        if existing.exists():
            return _validate_artifact(existing, commit, expected_files)
        os.replace(staging, existing)
        return _validate_artifact(existing, commit, expected_files)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
