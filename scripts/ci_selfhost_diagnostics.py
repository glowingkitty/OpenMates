#!/usr/bin/env python3
"""Write bounded, redacted diagnostics before a CI self-host install is removed."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote


SECRET_NAME = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|API_KEY|ACCESS_KEY|AUTH_KEY|ENCRYPTION_KEY|VAULT_KEY)",
    re.IGNORECASE,
)
ASSIGNMENT = re.compile(
    r"(?i)(\b[\w.-]*(?:secret|token|password|passwd|private[_-]?key|credential|api[_-]?key|access[_-]?key|auth[_-]?key)[\w.-]*\b[\"']?\s*[:=]\s*[\"']?)([^\s,;\"']+)"
)
LONG_TOKEN = re.compile(r"(?<![\w])(?:[A-Za-z0-9_+/=-]{48,}|[0-9a-fA-F]{32,})(?![\w])")
BEARER = re.compile(r"(?i)(\bBearer\s+)[^\s,;]+")
URL_CREDENTIALS = re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)")
MAX_INSTALLER_BYTES = 32_000
MAX_DOCKER_BYTES = 12_000
MAX_CONTAINERS = 12


def known_secrets(install_paths: list[Path], environ: dict[str, str]) -> set[str]:
    values: set[str] = set()
    for name, value in environ.items():
        if SECRET_NAME.search(name) and len(value) >= 4:
            values.add(value)
    for install in install_paths:
        for env_file in (install / ".env", install / "backend/core/.env"):
            try:
                lines = env_file.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                _, value = line.split("=", 1)
                value = value.strip().strip('"\'')
                if len(value) >= 4:
                    values.add(value)
    expanded = set(values)
    for value in values:
        expanded.add(quote(value, safe=""))
    return {value for value in expanded if len(value) >= 4}


def redact(raw: str, secrets: set[str]) -> str:
    text = raw
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = URL_CREDENTIALS.sub(r"\1[REDACTED]\2", text)
    text = BEARER.sub(r"\1[REDACTED]", text)
    text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
    return LONG_TOKEN.sub("[REDACTED]", text)


def tail(path: Path, limit: int) -> str:
    try:
        with path.open("rb") as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - limit))
            return source.read(limit).decode(errors="replace")
    except OSError:
        return "(unavailable)"


def command(args: list[str], limit: int = MAX_DOCKER_BYTES) -> str:
    try:
        result = subprocess.run(args, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "(unavailable)"
    output = (result.stdout + result.stderr)[-limit:]
    return output.decode(errors="replace")


def collect(workspace: Path, environ: dict[str, str]) -> str:
    installs = [Path(environ.get(key, default)) for key, default in (
        ("SOURCE_INSTALL_PATH", "/tmp/openmates-selfhost-source"),
        ("IMAGE_INSTALL_PATH", "/tmp/openmates-selfhost-image"),
    )]
    sections = ["Self-host install diagnostic snapshot"]
    for label, install in zip(("source", "image"), installs):
        sections.append(f"[{label} install] directory={install.is_dir()} env={(install / '.env').is_file()}")
    for name in ("selfhost-source-timing.json", "selfhost-image-timing.json"):
        sections.append(f"[timing] {name}: {tail(workspace / 'test-results' / name, 2000)}")
    sections.append("[installer tail]\n" + tail(workspace / "test-results/ci-private/installer.log", MAX_INSTALLER_BYTES))
    sections.append("[docker ps]\n" + command(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Image}}|{{.Status}}"], 4000))
    ids = command(["docker", "ps", "-aq"], 2000).splitlines()[:MAX_CONTAINERS]
    # Auth route exceptions can be hidden when worker containers fill the
    # bounded generic list. Always retain the API and CMS tails as well.
    for service in ("api", "cms"):
        service_id = command(["docker", "inspect", "--format", "{{.Id}}", service], 200).strip()
        if re.fullmatch(r"[0-9a-f]{12,64}", service_id) and service_id not in ids:
            ids.append(service_id)
    for container_id in ids:
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            continue
        identity = command(["docker", "inspect", "--format", "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", container_id], 500)
        log_tail = "180" if "/api|" in identity or "/cms|" in identity else "80"
        sections.append(f"[container {container_id[:12]} {identity.strip()}]\n" + command(["docker", "logs", "--tail", log_tail, container_id]))
    return redact("\n".join(sections), known_secrets(installs, environ))


def main() -> int:
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    output = workspace / "test-results/ci-stack.log"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(collect(workspace, dict(os.environ)))
    print(f"Sanitized self-host diagnostics saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
