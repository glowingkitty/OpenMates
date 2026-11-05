#!/usr/bin/env python3
"""Classify heavy local build/test/benchmark commands for the Bash guard.

The shared dev server (16 cores, 31 GB, no swap) was driven to load 140-363
with <1 GB available by parallel agent lanes compiling Rust, running
Playwright/Chromium benchmarks and vitest locally at the same time. Heavy
commands may run on the server only through `scripts/heavy_slot.py run -- <cmd>`,
which waits for a healthy host, limits concurrency to a few host-wide slots and
caps CPU/memory per run. Product E2E suites still use isolated GitHub CI.
`safe_bash_guard.py` calls `heavy_reason()` for every parsed invocation
(including package-script bodies) before its other checks.

Allowed directly: `cargo fmt|metadata|tree|...` (see CARGO_LIGHT), `rustfmt`,
version and help flags, pytest (light script/unit tests; still refused while the
host is overloaded). Legacy override for real-AI-inference runs on dev:
prefix the command with `OPENMATES_ALLOW_LOCAL_HEAVY=real-inference`; every use
is appended to logs/host-load-guard/events.jsonl and is still refused while
the host is overloaded.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

OVERRIDE_ENV = "OPENMATES_ALLOW_LOCAL_HEAVY"
OVERRIDE_VALUE = "real-inference"
OVERRIDE_TOKEN = f"{OVERRIDE_ENV}={OVERRIDE_VALUE}"

CI_HINT = (
    "Run builds, tests and benchmarks on the dev server through the resource-limited wrapper: "
    "python3 scripts/heavy_slot.py run -- <command> (waits for a healthy host and a free slot; "
    "caps CPU and memory). Or use isolated GitHub CI: python3 scripts/sessions.py ci-source -> "
    "python3 scripts/ci_coordinator.py submit --mode rust-check|rust-wasm|rust-native-dev|vitest|pytest|e2e "
    "... -> python3 scripts/ci_coordinator.py wait <id>."
)

# Cargo subcommands that do not compile crates.
CARGO_LIGHT = {
    "fmt", "metadata", "tree", "locate-project", "pkgid", "update", "generate-lockfile",
    "fetch", "clean", "search", "version", "help", "verify-project", "read-manifest",
}
CARGO_OPTIONS_WITH_VALUES = {"-C", "-Z", "--config", "--color", "--manifest-path"}
INFO_FLAGS = {"--version", "-V", "--help", "-h", "help"}
RUST_COMPILERS = {"rustc", "wasm-pack", "wasm-bindgen", "cross", "cargo-nextest", "cargo-llvm-cov"}
MATURIN_HEAVY = {"build", "develop", "publish"}
PACKAGE_MANAGERS = {"pnpm", "npm", "yarn"}
PACKAGE_MANAGER_OPTIONS_WITH_VALUES = {
    # pnpm's -w means --workspace-root (no value); npm/yarn's -w takes a workspace name.
    "pnpm": {"-C", "--dir", "--prefix", "--filter", "-F"},
    "npm": {"-C", "--prefix", "-w", "--workspace"},
    "yarn": {"--cwd"},
}
HEAVY_SCRIPT_NAME = re.compile(r"^(build|test|t|bench|benchmark|e2e|playwright|vitest)(:|$)")
BROWSERS = {"chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "chrome-headless-shell"}
BENCH_SCRIPT = re.compile(r"(^|[/_.-])(web_rust_bench|rust_bench|bench|benchmark)([/_.-]|$)", re.IGNORECASE)
INTERPRETERS = {"node", "python", "python3", "bun", "deno", "tsx", "ts-node"}


def _first_non_option(args: list[str], options_with_values: set[str]) -> tuple[str, int]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            continue
        if arg.startswith("+"):  # cargo +toolchain
            index += 1
            continue
        if arg.startswith("-"):
            index += 2 if arg in options_with_values else 1
            continue
        return arg, index
    return "", len(args)


def _info_only(args: list[str]) -> bool:
    return bool(args) and all(arg in INFO_FLAGS for arg in args)


def _cargo_reason(args: list[str]) -> str | None:
    if _info_only(args) or "--list" in args:
        return None
    sub, _ = _first_non_option(args, CARGO_OPTIONS_WITH_VALUES)
    if not sub or sub in CARGO_LIGHT:
        return None
    return f"cargo {sub} compiles Rust locally"


def _package_manager_reason(command: str, args: list[str]) -> str | None:
    action, index = _first_non_option(args, PACKAGE_MANAGER_OPTIONS_WITH_VALUES[command])
    rest = args[index + 1 :]
    if action in {"exec", "x", "dlx"}:
        binary, binary_index = _first_non_option(rest, set())
        return heavy_reason(Path(binary).name, rest[binary_index + 1 :]) if binary else None
    if action in {"run", "run-script", "workspace"}:
        if action == "workspace":  # yarn workspace <name> <script>
            rest = rest[1:]
        action, _ = _first_non_option(rest, set())
    elif action == "turbo":
        return heavy_reason("turbo", rest)
    if action and HEAVY_SCRIPT_NAME.match(action):
        return f"{command} {action} runs a build/test script locally"
    # Bare binaries via `pnpm vitest` / `yarn playwright`.
    return heavy_reason(action, rest) if action in {"vitest", "playwright", "vite", "svelte-kit", "wasm-pack"} else None


def _script_path_reason(path: str) -> str | None:
    if BENCH_SCRIPT.search(path) or BENCH_SCRIPT.search(Path(path).name):
        return f"{path} is a local benchmark (headless browser / native load)"
    return None


def heavy_reason(command: str, args: list[str]) -> str | None:
    """Return why `command args` is heavy local work, or None when allowed."""
    if not command or _info_only(args):
        return None
    if command == "cargo":
        return _cargo_reason(args)
    if command in RUST_COMPILERS:
        if command == "rustc" and any(arg.startswith("--print") for arg in args):
            return None
        return f"{command} compiles Rust/WASM locally"
    if command == "maturin" and args and args[0] in MATURIN_HEAVY:
        return f"maturin {args[0]} compiles Rust locally"
    if command == "vitest":
        return "vitest runs locally"
    if command == "playwright":
        return "playwright runs browsers locally"
    if command == "vite" and _first_non_option(args, set())[0] == "build":
        return "vite build runs locally"
    if command == "svelte-kit" and _first_non_option(args, set())[0] == "build":
        return "svelte-kit build runs locally"
    if command == "turbo":
        task = _first_non_option(args[1:] if args[:1] == ["run"] else args, set())[0]
        if task and HEAVY_SCRIPT_NAME.match(task):
            return f"turbo {task} runs a build/test task locally"
        return None
    if command == "npx":
        binary, index = _first_non_option(args, {"-p", "--package", "-c", "--call"})
        return heavy_reason(Path(binary).name, args[index + 1 :]) if binary else None
    if command in PACKAGE_MANAGERS:
        return _package_manager_reason(command, args)
    if command in BROWSERS and any(arg.startswith("--headless") for arg in args):
        return f"{command} --headless runs a local browser"
    if command in INTERPRETERS:
        if command.startswith("python") and len(args) >= 2 and args[0] == "-m":
            return _script_path_reason(args[1].replace(".", "/"))
        target, _ = _first_non_option(args, set())
        return _script_path_reason(target) if target else None
    if "/" in command or command.endswith((".sh", ".py", ".cjs", ".mjs", ".js")):
        return _script_path_reason(command)
    return None


def override_requested(tokens: list[str]) -> bool:
    return OVERRIDE_TOKEN in tokens or os.environ.get(OVERRIDE_ENV) == OVERRIDE_VALUE


def block_message(reason: str) -> str:
    return f"BLOCKED: {reason}. {CI_HINT}"
