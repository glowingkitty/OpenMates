"""Runtime configuration for the security monitoring orchestration lane.

Everything environment-specific (webhook URLs, limits, smoke command) comes from
the process environment or the repository `.env`; tracked code holds only
neutral defaults. State lives under logs/security-monitoring/ (gitignored).
See specifications/architecture/security-monitoring/specification.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

WORKTREE_MARKER = ".openmates-agent-worktrees"

# Paths a guarded auto-fix may never touch (autofix.guarded-dev-only).
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    ".claude/",
    ".github/workflows/",
    "deployment/",
    "scripts/security_monitoring/",
    "scripts/security_monitor.py",
    "CLAUDE.md",
)
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = ("secret", "vault")


def is_forbidden_path(path: str) -> bool:
    """True when a repo-relative path is outside what an auto-fix may change."""
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    lowered = normalized.lower()
    if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    name = lowered.rsplit("/", 1)[-1]
    if name.startswith(".env") or "/.env" in lowered:
        return True
    return any(token in lowered for token in FORBIDDEN_SUBSTRINGS)


def is_repo_relative(path: str) -> bool:
    if not path or path.startswith(("/", "~")) or "\\" in path or "\x00" in path:
        return False
    return ".." not in Path(path).parts


def canonical_root(start: Path | None = None) -> Path:
    """The canonical dev checkout, even when invoked from a session worktree."""
    root = (start or Path(__file__).resolve().parents[2]).resolve()
    if WORKTREE_MARKER in root.parts:
        return Path(*root.parts[: root.parts.index(WORKTREE_MARKER)])
    return root


def dotenv_value(root: Path, key: str) -> str:
    """Read one key from the environment, else from `<root>/.env` (never logged)."""
    if os.environ.get(key):
        return os.environ[key]
    env_path = root / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("\"'")
    return ""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def dry_run_enabled() -> bool:
    return os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    project_root: Path
    state_dir: Path
    triage_runs_per_day: int = 6
    autofixes_per_day: int = 3
    triage_timeout_seconds: int = 25 * 60
    fix_timeout_seconds: int = 90 * 60
    triage_budget_usd: float = 5.0
    fix_budget_usd: float = 10.0
    triage_max_attempts: int = 2
    triage_max_batch: int = 20
    watcher_stale_hours: int = 2
    first_run_lookback_hours: int = 24
    claude_bin: str = "claude"
    triage_model: str = ""
    dev_smoke_command: str = "python3 scripts/tests.py run --hourly-dev"
    dry_run: bool = False
    no_agents: bool = False

    @property
    def state_db(self) -> Path:
        return self.state_dir / "state.sqlite3"

    @property
    def hosts_dir(self) -> Path:
        return self.state_dir / "hosts"

    @property
    def delivery_ledger(self) -> Path:
        return self.state_dir / "delivery.sqlite3"

    @property
    def transcripts_dir(self) -> Path:
        return self.state_dir / "transcripts"

    @property
    def expected_ssh_file(self) -> Path:
        return self.state_dir / "expected_ssh.json"


def load_settings(*, project_root: Path | None = None, dry_run: bool | None = None, no_agents: bool = False) -> Settings:
    root = canonical_root(project_root)
    state_dir = Path(os.environ.get("SECURITY_MONITORING_DIR") or root / "logs" / "security-monitoring")
    return Settings(
        project_root=root,
        state_dir=state_dir,
        triage_runs_per_day=_int_env("SECURITY_MONITORING_TRIAGE_RUNS_PER_DAY", 6),
        autofixes_per_day=_int_env("SECURITY_MONITORING_AUTOFIXES_PER_DAY", 3),
        triage_timeout_seconds=_int_env("SECURITY_MONITORING_TRIAGE_TIMEOUT_SECONDS", 25 * 60),
        fix_timeout_seconds=_int_env("SECURITY_MONITORING_FIX_TIMEOUT_SECONDS", 90 * 60),
        triage_budget_usd=_float_env("SECURITY_MONITORING_TRIAGE_BUDGET_USD", 5.0),
        fix_budget_usd=_float_env("SECURITY_MONITORING_FIX_BUDGET_USD", 10.0),
        triage_max_attempts=_int_env("SECURITY_MONITORING_TRIAGE_MAX_ATTEMPTS", 2),
        triage_max_batch=max(1, _int_env("SECURITY_TRIAGE_MAX_BATCH", 20)),
        claude_bin=os.environ.get("SECURITY_MONITORING_CLAUDE_BIN", "claude"),
        triage_model=os.environ.get("SECURITY_MONITORING_MODEL", ""),
        dev_smoke_command=os.environ.get("SECURITY_MONITORING_DEV_SMOKE_CMD", "python3 scripts/tests.py run --hourly-dev"),
        dry_run=dry_run_enabled() if dry_run is None else dry_run,
        no_agents=no_agents,
    )


def git_head(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


# Credential stores outside the repository (never readable by triage or fix chats).
CREDENTIAL_READ_DENIES: tuple[str, ...] = tuple(
    f"Read({p})"
    for p in (
        "**/.env*", "**/*secret*", "**/*.pem", "**/*.key", "**/logs/**",
        "~/.ssh/**", "~/.claude/**", "~/.claude.json", "~/.config/**", "~/.codex/**", "~/.cursor/**",
        "~/.opencode/**", "~/.gnupg/**", "~/.aws/**", "~/.docker/**", "~/.vercel/**", "~/.npmrc",
        "~/.netrc", "~/.git-credentials", "~/.pypirc", "~/.cargo/credentials*", "~/.local/share/**",
        "~/.bash_history", "~/.zsh_history", "/proc/**", "/etc/shadow", "/etc/sudoers*", "/root/**",
    )
)
