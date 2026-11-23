#!/usr/bin/env python3
"""Prepared E2B CI runner templates, one per dependency hash.

The plain `openmates-ci-runner` template (scripts/ci_e2b_runner.py) holds only OS
packages and the Actions runner; every job then installs Node dependencies,
Playwright browsers, Rust and wasm-bindgen from scratch. A dependency template
`openmates-ci-runner-<hash12>` adds those, so a job on it only restores source.

The hash covers the template definition (steps and base), RUNNER_VERSION and the
inputs of what is baked, read from a commit: pnpm-lock.yaml, package.json,
pnpm-workspace.yaml, the Node version the workflow stages
(scripts/ci_download_node_supplier.py), the Playwright version from the lockfile,
Rust, wasm-bindgen and the recorder apt packages. No source and no secrets are
baked; the workflow still stages and verifies its own Node and checks the source.

Usage (E2B SDK venv, see ci_e2b_runner.VENV_PYTHON):
  ci_e2b_runner.py template --deps [--commit <sha>]   build if missing, keep newest 3
  ci_e2b_runner.py warm                               cheap no-op when origin/dev is covered
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEPS_PREFIX = "openmates-ci-runner-"
KEEP_DEPS_TEMPLATES = 3
RUST_VERSION = "1.98.1"
WASM_BINDGEN_VERSION = "0.2.129"
RECORDER_PACKAGES = ["zutty", "fonts-dejavu-core", "x11-xserver-utils", "xdotool", "ffmpeg", "xvfb", "util-linux"]
HASH_FILES = ("pnpm-lock.yaml", "package.json", "pnpm-workspace.yaml")
NODE_SUPPLIER = "scripts/ci_download_node_supplier.py"
API_URL = "https://api.e2b.app"
ROOT = Path(__file__).resolve().parents[1]


def git_show(commit: str, path: str, root: Path = ROOT) -> str:
    """File content at `commit`, '' when the file does not exist there."""
    result = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def playwright_version(lockfile: str) -> str:
    match = re.search(r"^  '?@playwright/test@(\d+\.\d+\.\d+)'?:", lockfile, re.MULTILINE)
    return match.group(1) if match else ""


def node_version(supplier_source: str) -> str:
    match = re.search(r'^NODE_VERSION = "v([^"]+)"', supplier_source, re.MULTILINE)
    return match.group(1) if match else ""


def package_manager(package_json: str) -> str:
    try:
        value = json.loads(package_json).get("packageManager", "")
    except ValueError:
        return ""
    return value.removeprefix("pnpm@") if value.startswith("pnpm@") else ""


def read_inputs(commit: str, root: Path = ROOT) -> dict:
    """Everything baked into the template, as read from `commit`."""
    files = {name: git_show(commit, name, root) for name in HASH_FILES}
    if not files["pnpm-lock.yaml"]:
        raise ValueError(f"pnpm-lock.yaml missing at {commit[:12]}")
    inputs = {
        "files": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(files.items())},
        "node": node_version(git_show(commit, NODE_SUPPLIER, root)),
        "pnpm": package_manager(files["package.json"]),
        "playwright": playwright_version(files["pnpm-lock.yaml"]),
        "rust": RUST_VERSION,
        "wasm_bindgen": WASM_BINDGEN_VERSION,
        "recorder": sorted(RECORDER_PACKAGES),
    }
    missing = [key for key in ("node", "pnpm", "playwright") if not inputs[key]]
    if missing:
        raise ValueError(f"cannot read {', '.join(missing)} at {commit[:12]}")
    return inputs


def bake_steps(inputs: dict) -> list[tuple[str, str]]:
    """(user, shell command) steps added on top of the plain runner template."""
    pw, node = inputs["playwright"], inputs["node"]
    tool = f"rustup run {RUST_VERSION}"
    return [
        ("root", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
                 + " ".join(sorted(RECORDER_PACKAGES)) + " && rm -rf /var/lib/apt/lists/*"),
        ("root", f"curl -fsSL https://nodejs.org/dist/v{node}/node-v{node}-linux-x64.tar.xz "
                 f"| tar xJ -C /usr/local --strip-components=1 && npm install -g pnpm@{inputs['pnpm']}"),
        ("root", f"npx --yes playwright@{pw} install-deps chromium webkit && rm -rf /var/lib/apt/lists/*"),
        ("user", f"npx --yes playwright@{pw} install chromium webkit"),
        ("user", f"rustup toolchain install {RUST_VERSION} --profile minimal --target wasm32-unknown-unknown && "
                 f"rustup default {RUST_VERSION} && {tool} cargo install wasm-bindgen-cli "
                 f"--version {WASM_BINDGEN_VERSION} --locked && rm -rf ~/.cargo/registry ~/.cargo/git"),
    ]


def pnpm_fetch_step(commit: str) -> tuple[str, str]:
    """Prefetch the pnpm store from the lockfile; the checkout is deleted again."""
    return ("user", "rm -rf /tmp/lockdir && mkdir /tmp/lockdir && cd /tmp/lockdir && git init -q && "
                    "git remote add origin https://github.com/glowingkitty/OpenMates.git && "
                    f"git fetch -q --depth 1 origin {commit} && "
                    + " && ".join(f"git show FETCH_HEAD:{name} > {name}" for name in HASH_FILES if name != "package.json")
                    + " && git show FETCH_HEAD:package.json > package.json && pnpm fetch && cd / && rm -rf /tmp/lockdir")


def definition_digest(base_steps: list[tuple[str, str]], inputs: dict, runner_version: str) -> str:
    """Hash of the template definition + runner version + baked inputs (stable, order-sensitive)."""
    payload = json.dumps({"base": base_steps, "bake": bake_steps(inputs), "runner": runner_version,
                          "inputs": inputs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def alias_for(digest: str) -> str:
    return f"{DEPS_PREFIX}{digest}"


def is_deps_alias(name: str) -> bool:
    return re.fullmatch(re.escape(DEPS_PREFIX) + r"[0-9a-f]{12}", name) is not None


def source_alias(commit: str, base_steps, runner_version: str, root: Path = ROOT) -> str:
    return alias_for(definition_digest(base_steps, read_inputs(commit, root), runner_version))


# ---- E2B REST (list/delete are not in the SDK) --------------------------------

def _api(method: str, path: str, api_key: str):
    request = urllib.request.Request(API_URL + path, method=method, headers={"X-API-KEY": api_key})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    return json.loads(body) if body else None


def list_deps_templates(api_key: str) -> list[dict]:
    """Dependency templates, newest first: {id, alias, created}."""
    rows = []
    for item in _api("GET", "/templates", api_key) or []:
        names = list(item.get("aliases") or []) + list(item.get("names") or [])
        alias = next((name.split("/")[-1].split(":")[0] for name in names if is_deps_alias(name.split("/")[-1].split(":")[0])), "")
        if alias:
            rows.append({"id": item["templateID"], "alias": alias, "created": item.get("createdAt", "")})
    return sorted(rows, key=lambda row: row["created"], reverse=True)


def prune(rows: list[dict], keep: int, delete) -> list[str]:
    """Delete all but the newest `keep` dependency templates; never anything else."""
    removed = []
    for row in sorted(rows, key=lambda r: r["created"], reverse=True)[keep:]:
        if is_deps_alias(row["alias"]):
            delete(row["id"])
            removed.append(row["alias"])
    return removed


def template_exists(alias: str) -> bool:
    from e2b import Template

    import heavy_remote

    return bool(Template.alias_exists(alias, api_key=heavy_remote.e2b_api_key()))


def resolve_commit(ref: str | None, root: Path = ROOT) -> str:
    if ref:
        return subprocess.run(["git", "-C", str(root), "rev-parse", ref], check=True, capture_output=True,
                              text=True).stdout.strip()
    subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin", "dev"], check=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "origin/dev"], check=True, capture_output=True,
                          text=True).stdout.strip()


def build_deps_template(commit: str, *, force: bool = False, quiet_if_present: bool = False) -> int:
    """Build the dependency template for `commit` unless it exists, then prune."""
    from e2b import Template

    import ci_e2b_runner as runner
    import heavy_remote

    inputs = read_inputs(commit)
    alias = alias_for(definition_digest(runner.base_steps(), inputs, runner.RUNNER_VERSION))
    key = heavy_remote.e2b_api_key()
    if template_exists(alias) and not force:
        if not quiet_if_present:
            print(f"ci_e2b_template: {alias} already exists for {commit[:12]}")
    else:
        started = time.monotonic()
        template = runner.template_definition()
        for user, command in [*bake_steps(inputs), pnpm_fetch_step(commit)]:
            template = template.set_user(user).run_cmd(command)
        template = template.set_user("user").set_workdir("/home/user")
        info = Template.build(template, name=alias, cpu_count=runner.SANDBOX_CPUS, memory_mb=runner.SANDBOX_MEMORY_MB,
                              api_key=key)
        print(f"ci_e2b_template: built {alias} {info.template_id} in {time.monotonic() - started:.0f}s")
    removed = prune(list_deps_templates(key), KEEP_DEPS_TEMPLATES, lambda tid: _api("DELETE", f"/templates/{tid}", key))
    if removed:
        print(f"ci_e2b_template: removed old {', '.join(removed)}")
    return 0


def warm() -> int:
    """For a timer: build only when current origin/dev has no template yet."""
    return build_deps_template(resolve_commit(None), quiet_if_present=True)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(warm())
