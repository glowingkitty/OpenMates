"""Run a build/test/benchmark command for OpenMates development within resource limits.

Remote first: `cargo test|check|clippy|build` (host target), `vitest`, the
translation build, `svelte-check` and Playwright runs (see heavy_remote_plan.py)
run in an E2B sandbox (8 CPUs, 8 GB) through heavy_remote.py, without a local
slot, and copy back the files they produce. Dev E2B use is capped by
e2b_dev_capacity.py: at most 70% of the team's concurrency limit (the rest
stays free for product usage) and a daily budget. When the cap is reached,
remote kinds in QUEUE_REMOTE_KINDS wait in the E2B queue; lighter kinds fall
back to the local queue. A remote-eligible run never waits for host memory or
a local slot: it goes to E2B right away. Only when the remote run is unavailable
(no SDK venv, no key, no sandbox, lost connection, budget used up) does
heavy_slot say so and run the command locally; each such fallback is logged as a
`heavy_remote_fallback` event in the host-load-guard log. `--local`,
OPENMATES_HEAVY_REMOTE=0 or the file REMOTE_DISABLED_FILE force local runs
(also logged).

Browser proofs against the dev stack (scripts/design_embroidery_web_real_test.py
and the real tests built on it) run remote too: the account lease and draft
guard stay on the host, the Playwright run gets the leased dev account's env
(PLAYWRIGHT_*, OPENMATES_TEST_ACCOUNT_*, OPENMATES_PERSONAL_TEST_ACOUNT_*,
OPENMATES_PROOF_*, E2E_*, plus the names in OPENMATES_HEAVY_REMOTE_ENV), the
/tmp folders in OPENMATES_HEAVY_REMOTE_DIRS (comma-separated, e.g. generated
speech files) are copied in, and the proof folder's results, videos and log
come back. `--run-timeout` limits the run itself; `--timeout` is the wait for
an E2B (or local) slot.

What stays on the host, and why:
- docker, xcodebuild: need this host's Docker daemon and dev stack, or macOS
  (Apple lanes run on GitHub macos runners);
- `vite`/`svelte-kit build`/`pnpm build`, wasm-pack and cargo for a non-host
  target or pinned toolchain: the sandbox template has only the host Rust target
  and their outputs are too large to copy back;
- vitest snapshot updates (`-u`): they are written and reviewed in the worktree;
- shell payloads with file redirection, `&` or substitution, and any other
  command: their side effects cannot be mapped into the sandbox;
- a Playwright run whose config or inputs live outside the worktree and /tmp
  (e.g. a host-only Chrome build in OPENMATES_PROOF_BROWSER). On 2026-11-12, 44 of 376 local runs in
24 hours were OOM-killed by the 6 GB cap; the same `cargo test -p
openmates-sdk` finished in E2B in about 4 minutes.

Local runs (everything else, and fallbacks) share the dev server (16 cores,
31 GB, no swap), which was once driven to load 140-363 by parallel agents
compiling Rust and running browsers at the same time. The wrapper:

- waits until `host_load_guard` reports the host healthy,
- sizes each run by its class (CLASSES): `heavy` (builds, Rust, svelte-check;
  6 GB, at most MAX_SLOTS at once), `browser` (one Playwright run; 3 GB) and
  `light` (translation build, pytest, tsc, eslint; 2 GB); browser and light
  runs share LIGHT_SLOTS slots of their own. On 2026-11-13 one 6 GB
  reservation for every run kept translation builds and single-browser runs
  waiting for hours with 7-8.7 GB free,
- admits a run only when the host has room for its memory cap on top of the
  overload threshold, counting the caps of runs that started less than
  SETTLE_SECONDS ago (their memory is not in use yet). On 2026-11-11 two runs
  admitted in the same second grew to ~9 GB together with 8 GB available and
  froze the host,
- runs the command in a systemd user scope capped at its class's CPU quota and
  memory, at low CPU/IO priority, with CARGO_BUILD_JOBS limited.

Usage:
  python3 scripts/heavy_slot.py run [--timeout S] [--run-timeout S] [--local] -- cargo build --release
  python3 scripts/heavy_slot.py status
  python3 scripts/heavy_slot.py remote-setup      # one-time: E2B SDK venv
  python3 scripts/heavy_slot.py remote-template   # build/refresh the sandbox template

Exit code is the wrapped command's exit code; 3 when the host stayed
overloaded, or no local slot or E2B slot became free, before --timeout.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2b_dev_capacity  # noqa: E402 - sibling module, standard library only
import host_load_guard  # noqa: E402 - sibling module; path set up above for direct-file loading
import heavy_remote_plan  # noqa: E402 - sibling module, standard library only

MAX_SLOTS = 2
LIGHT_SLOTS = 4
MEMORY_MAX_BYTES = 6 * host_load_guard.GIB
# class -> (CPU quota, memory cap in GiB). Peaks seen: translation build well
# under 1 GB, one headless Chromium with video 1-2 GB.
CLASSES = {"heavy": ("400%", 6), "browser": ("200%", 3), "light": ("200%", 2)}
LIGHT_PATTERNS = (
    re.compile(r"build[:-]translations"),
    re.compile(r"(^|[\s/])(pytest|tsc|eslint|tsup|ruff)(\s|$)"),
    re.compile(r"-m pytest\b"),
    re.compile(r"\bnode --test\b"),
    re.compile(r"\bpip install\b"),
)
BROWSER_PATTERN = re.compile(r"\bplaywright(/test/cli\.js)? test\b")
HEAVY_PATTERN = re.compile(r"\b(cargo|rustc|wasm-pack|docker|svelte-check|vite|svelte-kit|xcodebuild)\b"
                           r"|build-xcframework|pnpm (run )?build\b|npm run build(?!:translations)")
# Remote kinds that wait in the E2B queue instead of falling back to the local queue.
QUEUE_REMOTE_KINDS = frozenset({"cargo", "vitest", "playwright"})
SETTLE_SECONDS = 180
CARGO_JOBS = "4"
DEFAULT_TIMEOUT_SECONDS = 3600
POLL_SECONDS = 5
EXIT_UNAVAILABLE = 3
SCRIPTS_DIR = Path(__file__).resolve().parent


def say(message: str) -> None:
    print(f"heavy_slot: {message}", file=sys.stderr, flush=True)


def command_class(command: list[str]) -> str:
    """`heavy`, `browser` or `light`: decides the local memory cap and slot pool."""
    text = " ".join(command)
    if HEAVY_PATTERN.search(text):
        return "heavy"
    if BROWSER_PATTERN.search(text):
        return "browser"
    if any(pattern.search(text) for pattern in LIGHT_PATTERNS):
        return "light"
    return "heavy"


def class_cap_bytes(cls: str) -> int:
    return CLASSES[cls][1] * host_load_guard.GIB


def slot_dir() -> Path:
    path = host_load_guard.state_dir() / "heavy-slots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pools(directory: Path) -> dict[str, tuple[Path, int]]:
    """Slot pools: heavy runs, and browser/light runs."""
    light = directory / "light"
    light.mkdir(parents=True, exist_ok=True)
    return {"heavy": (directory, MAX_SLOTS), "light": (light, LIGHT_SLOTS)}


def try_acquire(directory: Path, count: int = MAX_SLOTS) -> tuple[int, int] | None:
    """Return (fd, slot) for a free slot, or None when all slots are held."""
    directory.mkdir(parents=True, exist_ok=True)
    for slot in range(count):
        fd = os.open(directory / f"slot-{slot}.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        return fd, slot
    return None


def _slot_record(text: str) -> dict:
    """Slot file content: JSON {"cap", "class", "command"}; older runs wrote the bare command."""
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        record = None
    if not isinstance(record, dict):
        return {"cap": MEMORY_MAX_BYTES, "command": text[:300]}
    return record


def holders(directory: Path, count: int = MAX_SLOTS) -> list[dict]:
    result = []
    for slot in range(count):
        path = directory / f"slot-{slot}.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            record = _slot_record(path.read_text(errors="replace"))
            result.append({"slot": slot, "busy": True, "command": str(record.get("command", ""))[:300],
                           "cap": int(record.get("cap", MEMORY_MAX_BYTES)), "started": path.stat().st_mtime})
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            result.append({"slot": slot, "busy": False})
        finally:
            os.close(fd)
    return result


def recent_reserved(directory: Path, now: float) -> int:
    """Bytes reserved by busy slots (any pool) whose run started less than SETTLE_SECONDS ago."""
    total = 0
    for pool_dir, count in pools(directory).values():
        for slot in holders(pool_dir, count):
            if slot["busy"] and now - slot["started"] < SETTLE_SECONDS:
                total += slot["cap"]
    return total


def memory_shortfall(mem_available_bytes: int, recent_bytes: int,
                     cap_bytes: int = MEMORY_MAX_BYTES) -> str | None:
    """Return why a new run does not fit in memory, or None when it does."""
    needed = host_load_guard.THRESHOLDS.block_mem_available_bytes + cap_bytes + recent_bytes
    if mem_available_bytes >= needed:
        return None
    gib = host_load_guard.GIB
    return (f"MemAvailable {mem_available_bytes / gib:.1f} GiB < {needed / gib:.1f} GiB needed "
            f"(run cap {cap_bytes / gib:.0f} GiB + {recent_bytes / gib:.0f} GiB for runs just started "
            f"+ overload threshold)")


def admit(directory: Path, cls: str = "heavy", command: str = "") -> tuple[tuple[int, int] | None, str]:
    """Take a slot of the class's pool when the host is healthy and has memory for the run.

    Admission is serialized by a gate lock, and the slot file is stamped before
    the gate is released, so two waiting runs cannot both count the same free memory.
    """
    cap = class_cap_bytes(cls)
    pool_dir, count = pools(directory)["heavy" if cls == "heavy" else "light"]
    gate = os.open(directory / "admission.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(gate, fcntl.LOCK_EX)
        sample, decision = host_load_guard.current_decision()
        if decision.overloaded:
            return None, "host overloaded: " + "; ".join(decision.reasons)
        shortfall = memory_shortfall(sample.mem_available_bytes, recent_reserved(directory, time.time()), cap)
        if shortfall:
            return None, shortfall
        acquired = try_acquire(pool_dir, count)
        if acquired is None:
            return None, f"all {count} {'heavy' if cls == 'heavy' else 'browser/light'} slots busy"
        os.ftruncate(acquired[0], 0)
        os.write(acquired[0], json.dumps({"cap": cap, "class": cls, "command": command[:300]}).encode())
        os.utime(acquired[0])  # mtime = start time for recent_reserved()
        return acquired, ""
    finally:
        fcntl.flock(gate, fcntl.LOCK_UN)
        os.close(gate)


def wrapped_command(command: list[str], cls: str = "heavy") -> list[str]:
    limited = ["nice", "-n", "10"]
    if shutil.which("ionice"):
        limited = ["ionice", "-c", "3", *limited]
    if shutil.which("systemd-run") is None:
        raise SystemExit("heavy_slot: systemd-run is required to apply CPU and memory limits")
    quota, gib = CLASSES[cls]
    return [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "-p", f"CPUQuota={quota}", "-p", f"MemoryMax={gib}G", "-p", "MemorySwapMax=0",
        "--", *limited, *command,
    ]


REMOTE_EXIT_UNAVAILABLE = 75  # heavy_remote.EXIT_REMOTE_UNAVAILABLE (that module needs the E2B SDK)


def remote_venv_python() -> Path:
    return Path.home() / ".cache" / "openmates" / "heavy-remote" / "venv" / "bin" / "python"


def remote_disabled_file() -> Path:
    return host_load_guard.state_dir() / "heavy-remote.disabled"


def remote_disabled_reason(local: bool) -> str | None:
    if local:
        return "--local"
    if os.environ.get("OPENMATES_HEAVY_REMOTE") == "0":
        return "OPENMATES_HEAVY_REMOTE=0"
    if remote_disabled_file().exists():
        return f"{remote_disabled_file()} exists"
    if not remote_venv_python().exists():
        return "E2B SDK venv missing (python3 scripts/heavy_slot.py remote-setup)"
    return None


def worktree_root(cwd: Path) -> Path | None:
    result = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    root = Path(result.stdout.strip())
    return root if (root / "scripts" / "heavy_remote.py").exists() else None


CONFIG_SUFFIXES = (".cjs", ".mjs", ".js", ".ts", ".json")
ABSOLUTE_PATH = re.compile(r"(/home/[^\s\"'`]+)")


def command_root(command: list[str], cwd: Path) -> Path | None:
    """The worktree to sync: the cwd's; for a /tmp proof folder, the most specific
    worktree named by a command path or by the folder's config files (an agent
    worktree sits inside the canonical checkout, so the longest root wins)."""
    root = worktree_root(cwd)
    if root is not None:
        return root
    paths = [arg for arg in command if arg.startswith("/")]
    if str(cwd).startswith(heavy_remote_plan.EXTERNAL_ROOTS):
        for config in cwd.iterdir():
            if config.suffix in CONFIG_SUFFIXES and config.is_file() and config.stat().st_size < 1_000_000:
                paths += ABSOLUTE_PATH.findall(config.read_text(errors="replace"))
    roots = set()
    for value in paths:
        path = Path(value)
        folder = path if path.is_dir() else path.parent
        if folder.is_dir():
            found = worktree_root(folder)
            if found is not None:
                roots.add(found)
    return max(roots, key=lambda r: len(str(r)), default=None)


def remote_dirs() -> tuple[str, ...]:
    """/tmp folders named in OPENMATES_HEAVY_REMOTE_DIRS (comma-separated)."""
    return tuple(part.strip() for part in os.environ.get("OPENMATES_HEAVY_REMOTE_DIRS", "").split(",")
                 if part.strip())


def fallback(reason: str, command: str, kind: str, announce: bool = True) -> None:
    """A remote-eligible run goes local: say why and log it."""
    if announce:
        say(f"running locally: {reason}")
    host_load_guard.append_event(
        host_load_guard.state_dir(), "heavy_remote_fallback",
        {"reason": reason[:300], "kind": kind, "command": command[:500], "cwd": os.getcwd(),
         "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")},
    )


def try_remote(command: list[str], timeout: float, local: bool, run_timeout: float | None = None) -> int | None:
    """Run the command in E2B when eligible; None means run it locally.

    `timeout` bounds the wait for an E2B slot, `run_timeout` (default: `timeout`) the run."""
    cwd = Path.cwd()
    root = command_root(command, cwd)
    planned = (heavy_remote_plan.plan_command(command, cwd, root, host_load_guard.canonical_root(),
                                              remote_dirs())
               if root else None)
    if planned is None:
        if remote_dirs():
            say("OPENMATES_HEAVY_REMOTE_DIRS is set but this command cannot run in E2B; running locally")
        return None
    label = " ".join(command)
    disabled = remote_disabled_reason(local)
    if disabled:
        fallback(f"remote run disabled ({disabled})", label, planned.kind, announce=not local)
        return None
    over_budget = e2b_dev_capacity.budget_exhausted()
    if over_budget:
        fallback(over_budget, label, planned.kind)
        return None
    if planned.kind in QUEUE_REMOTE_KINDS:
        slot = e2b_dev_capacity.acquire(label, timeout, announce=say)
        if slot is None:
            say(f"gave up after {timeout:.0f}s in the E2B queue")
            return EXIT_UNAVAILABLE
    else:
        slot = e2b_dev_capacity.try_acquire(label)
        if slot is None:
            fallback("all dev E2B slots busy; light job uses the local queue", label, planned.kind)
            return None
    started = time.monotonic()
    with slot:
        code = subprocess.call([
            str(remote_venv_python()), str(SCRIPTS_DIR / "heavy_remote.py"), "--root", str(root),
            "--kind", planned.kind, "--cwd", planned.cwd, "--timeout", str(int(run_timeout or timeout)),
            "--shell", planned.shell,
            *[arg for folder in planned.external_dirs for arg in ("--external", folder)],
            *(["--cargo-build"] if planned.cargo_build else []),
        ])
    host_load_guard.append_event(
        host_load_guard.state_dir(), "heavy_remote_run",
        {"slot": slot.index, "kind": planned.kind, "command": label[:500], "cwd": str(cwd), "exit": code,
         "seconds": round(time.monotonic() - started, 1),
         "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")},
    )
    if code == REMOTE_EXIT_UNAVAILABLE:
        fallback("remote run unavailable (reason above)", label, planned.kind)
        return None
    return code


def run(command: list[str], timeout: float, local: bool = False, run_timeout: float | None = None) -> int:
    if not command:
        say("missing command after --")
        return 2
    remote_code = try_remote(command, timeout, local, run_timeout)
    if remote_code is not None:
        return remote_code
    if shutil.which(command[0]) is None:
        say(f"command not found on PATH: {command[0]}")
        return 127
    deadline = time.monotonic() + timeout
    directory = slot_dir()
    cls = command_class(command)
    announced = False
    while True:
        acquired, why = admit(directory, cls, " ".join(command))
        if acquired is not None:
            break
        if time.monotonic() >= deadline:
            say(f"gave up after timeout ({why})")
            return EXIT_UNAVAILABLE
        if not announced:
            say(f"waiting ({why})")
            announced = True
        time.sleep(POLL_SECONDS)
    fd, slot = acquired
    env = dict(os.environ, CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", CARGO_JOBS))
    host_load_guard.append_event(
        host_load_guard.state_dir(), "heavy_slot_run",
        {"slot": slot, "class": cls, "command": " ".join(command)[:500], "cwd": os.getcwd(),
         "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")},
    )
    try:
        return subprocess.call(wrapped_command(command, cls), env=env)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_parser.add_argument("--local", action="store_true", help="never run in E2B")
    run_parser.add_argument("--run-timeout", type=float,
                            help="limit of a remote run itself (default: --timeout, the slot wait)")
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    sub.add_parser("remote-setup")
    sub.add_parser("remote-template")
    args = parser.parse_args(argv)
    if args.action == "status":
        directory = slot_dir()
        light_dir, light_count = pools(directory)["light"]
        print(json.dumps({"classes": CLASSES, "heavy_slots": holders(directory),
                          "light_slots": holders(light_dir, light_count),
                          "remote": {"disabled": remote_disabled_reason(False), **e2b_dev_capacity.status()}},
                         indent=2))
        return 0
    if args.action == "remote-setup":
        return remote_setup()
    if args.action == "remote-template":
        if not remote_venv_python().exists():
            say("run remote-setup first")
            return 2
        return subprocess.call([str(remote_venv_python()), str(SCRIPTS_DIR / "heavy_remote_template.py")])
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run(command, args.timeout, args.local, args.run_timeout)


def remote_setup() -> int:
    """Create the E2B SDK venv used for remote runs (pinned SDK version)."""
    venv = remote_venv_python().parent.parent
    sdk = re.search(r'^E2B_SDK_VERSION = "([^"]+)"', (SCRIPTS_DIR / "heavy_remote.py").read_text(), re.M)
    if sdk is None:
        say("E2B_SDK_VERSION missing in heavy_remote.py")
        return 2
    if not remote_venv_python().exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    return subprocess.call([str(remote_venv_python()), "-m", "pip", "install", "-q", f"e2b=={sdk.group(1)}"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
