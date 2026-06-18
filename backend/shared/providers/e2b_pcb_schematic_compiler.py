# backend/shared/providers/e2b_pcb_schematic_compiler.py
#
# E2B wrapper for compiling untrusted atopile PCB schematic source. The API
# writes a minimal project, pins the compiler/docs version, runs `ato build`, and
# returns sanitized logs plus a small typed artifact manifest. It deliberately
# contains no OpenMates app-specific imports so it remains a pure provider.

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async, redact_execution_output


ATOPILE_PACKAGE_VERSION = "0.15.7"
ATOPILE_DOCS_VERSION = "0.15.7"
ATOPILE_PYTHON_VERSION = "3.14"
WORKSPACE_DIR = "/home/user/openmates-pcb"
INSTALL_TIMEOUT_SECONDS = 300
BUILD_TIMEOUT_SECONDS = 300
MAX_SOURCE_CHARS = 200_000
MAX_LOG_CHARS = 120_000
MAX_ARTIFACT_FILES = 40
MAX_ARTIFACT_CHARS = 500_000

ArtifactType = Literal[
    "kicad_project",
    "kicad_schematic",
    "kicad_pcb",
    "bom_csv",
    "pick_place_csv",
    "gerber_zip",
    "netlist",
    "build_log",
    "source_bundle",
]


@dataclass(frozen=True)
class PcbSchematicCompileRequest:
    source: str
    filename: str = "main.ato"
    module_name: str = "App"


@dataclass(frozen=True)
class PcbSchematicArtifact:
    id: str
    type: ArtifactType
    path: str
    name: str
    content: str = ""


@dataclass(frozen=True)
class PcbSchematicCompileResult:
    status: Literal["succeeded", "failed", "timeout"]
    exit_code: int | None
    logs: str
    artifact_manifest: dict[str, Any]
    artifacts: list[PcbSchematicArtifact] = field(default_factory=list)
    sandbox_id: str | None = None
    duration_seconds: float = 0.0


def _shell(command: str, timeout_seconds: int) -> str:
    return f"timeout {timeout_seconds}s bash -lc {shlex.quote(command)}"


def _sanitize_module_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "", value or "")
    if not name or not re.match(r"^[A-Za-z_]", name):
        return "App"
    return name[:80]


def _normalize_source_filename(value: str) -> str:
    name = (value or "main.ato").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "main.ato"
    if not name.lower().endswith(".ato"):
        name = f"{name}.ato"
    # E2B project uses main.ato as the entrypoint regardless of display filename.
    return "main.ato"


def _ato_yaml(module_name: str) -> str:
    return (
        f'requires-atopile: "^{ATOPILE_PACKAGE_VERSION}"\n\n'
        "paths:\n"
        "  src: ./\n"
        "  layout: ./layouts\n\n"
        "builds:\n"
        "  default:\n"
        f"    entry: main.ato:{module_name}\n"
    )


def _write_file(files_api: object, path: str, content: str) -> None:
    if hasattr(files_api, "write"):
        files_api.write(path, content)
        return
    if hasattr(files_api, "write_files"):
        files_api.write_files([{"path": path, "data": content}])
        return
    raise RuntimeError("E2B files API does not support file writes")


def _run_command(sandbox: object, command: str, timeout_seconds: int) -> tuple[int | None, str]:
    result = sandbox.commands.run(_shell(command, timeout_seconds), timeout=timeout_seconds + 10)
    stdout = str(getattr(result, "stdout", "") or "")
    stderr = str(getattr(result, "stderr", "") or "")
    return getattr(result, "exit_code", None), redact_execution_output(stdout + stderr)


def _artifact_type(path: str) -> ArtifactType | None:
    lower = path.lower()
    if lower.rsplit("/", 1)[-1] == ".ato":
        return None
    if lower.endswith(".kicad_pcb"):
        return "kicad_pcb"
    if lower.endswith(".kicad_sch"):
        return "kicad_schematic"
    if lower.endswith(".net"):
        return "netlist"
    if lower.endswith(".zip") and "gerber" in lower:
        return "gerber_zip"
    if lower.endswith(".csv") and "bom" in lower:
        return "bom_csv"
    if lower.endswith(".csv") and ("pick" in lower or "place" in lower or "pos" in lower):
        return "pick_place_csv"
    if lower.endswith((".ato", "ato.yaml")):
        return "source_bundle"
    return None


def _list_artifacts(files_api: object, path: str) -> list[Any]:
    if not hasattr(files_api, "list"):
        return []
    try:
        return list(files_api.list(path))
    except Exception:
        return []


def _read_artifact(files_api: object, path: str) -> str:
    if not hasattr(files_api, "read"):
        return ""
    try:
        value = files_api.read(path)
    except Exception:
        return ""
    if isinstance(value, bytes):
        return value[:MAX_ARTIFACT_CHARS].decode("utf-8", "replace")
    return str(value)[:MAX_ARTIFACT_CHARS]


def _collect_artifacts(files_api: object) -> list[PcbSchematicArtifact]:
    discovered = []
    for root in (WORKSPACE_DIR, f"{WORKSPACE_DIR}/build", f"{WORKSPACE_DIR}/manufacturing"):
        discovered.extend(_list_artifacts(files_api, root))

    artifacts: list[PcbSchematicArtifact] = []
    seen: set[str] = set()
    for item in discovered:
        if len(artifacts) >= MAX_ARTIFACT_FILES:
            break
        path = str(getattr(item, "path", "") or "")
        if not path or path in seen or bool(getattr(item, "is_dir", False)):
            continue
        artifact_type = _artifact_type(path)
        if artifact_type is None:
            continue
        seen.add(path)
        name = str(getattr(item, "name", "") or path.rsplit("/", 1)[-1])
        artifacts.append(
            PcbSchematicArtifact(
                id=f"artifact-{len(artifacts) + 1}",
                type=artifact_type,
                path=path,
                name=name,
                content=_read_artifact(files_api, path),
            )
        )
    return artifacts


def _artifact_manifest(artifacts: list[PcbSchematicArtifact], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "atopile_version": ATOPILE_PACKAGE_VERSION,
        "atopile_docs_version": ATOPILE_DOCS_VERSION,
        "bundle": {
            "id": "artifact-bundle",
            "type": "source_bundle",
            "name": "pcb-schematic-artifacts.zip",
        },
        "files": [
            {"id": artifact.id, "type": artifact.type, "path": artifact.path, "name": artifact.name}
            for artifact in artifacts
        ],
    }


def compile_pcb_schematic_in_e2b(
    request: PcbSchematicCompileRequest,
    api_key: str,
) -> PcbSchematicCompileResult:
    """Compile an atopile project in E2B and collect safe artifact metadata."""
    if ATOPILE_DOCS_VERSION != ATOPILE_PACKAGE_VERSION:
        raise RuntimeError("Atopile compiler/docs version mismatch")
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")
    if len(request.source) > MAX_SOURCE_CHARS:
        raise ValueError("Atopile source exceeds maximum allowed size")

    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc

    module_name = _sanitize_module_name(request.module_name)
    source_filename = _normalize_source_filename(request.filename)
    sandbox = None
    started_at = time.time()
    logs: list[str] = []
    exit_code: int | None = None

    try:
        sandbox = Sandbox.create(
            api_key=api_key,
            secure=True,
            allow_internet_access=True,
            network={"allow_public_traffic": False},
        )
        sandbox_id = getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", None)
        sandbox.commands.run(f"mkdir -p {shlex.quote(WORKSPACE_DIR)} {shlex.quote(f'{WORKSPACE_DIR}/layouts')}")
        _write_file(sandbox.files, f"{WORKSPACE_DIR}/ato.yaml", _ato_yaml(module_name))
        _write_file(sandbox.files, f"{WORKSPACE_DIR}/{source_filename}", request.source)

        install_command = (
            "python -m pip install --upgrade uv && "
            f"cd {shlex.quote(WORKSPACE_DIR)} && "
            f"uv venv --python {shlex.quote(ATOPILE_PYTHON_VERSION)} .venv && "
            f"uv pip install --python .venv/bin/python atopile=={shlex.quote(ATOPILE_PACKAGE_VERSION)}"
        )
        build_command = f"cd {shlex.quote(WORKSPACE_DIR)} && .venv/bin/ato build"

        for label, command, timeout_seconds in (
            ("Installing atopile", install_command, INSTALL_TIMEOUT_SECONDS),
            ("Building PCB project", build_command, BUILD_TIMEOUT_SECONDS),
        ):
            logs.append(f"{label}...\n")
            exit_code, output = _run_command(sandbox, command, timeout_seconds)
            logs.append(output)
            if exit_code not in (0, None):
                break

        status = "succeeded" if exit_code in (0, None) else "failed"
        artifacts = _collect_artifacts(sandbox.files) if status == "succeeded" else []
        joined_logs = redact_execution_output("".join(logs))[:MAX_LOG_CHARS]
        return PcbSchematicCompileResult(
            status=status,
            exit_code=exit_code,
            logs=joined_logs,
            artifact_manifest=_artifact_manifest(artifacts, status),
            artifacts=artifacts,
            sandbox_id=sandbox_id,
            duration_seconds=round(time.time() - started_at, 3),
        )
    finally:
        if sandbox is not None and hasattr(sandbox, "kill"):
            sandbox.kill()


__all__ = [
    "ATOPILE_DOCS_VERSION",
    "ATOPILE_PACKAGE_VERSION",
    "PcbSchematicArtifact",
    "PcbSchematicCompileRequest",
    "PcbSchematicCompileResult",
    "compile_pcb_schematic_in_e2b",
    "get_e2b_api_key_async",
]
