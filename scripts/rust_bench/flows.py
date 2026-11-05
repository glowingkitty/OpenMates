"""Arm isolation (per-CLI profile/env) and the measured CLI flows.

Each arm owns one profile root directory:

    <profile>/state   OPENMATES_STATE_DIR (both CLIs) and Rust --state-dir
    <profile>/home    HOME, so neither CLI can fall back to ~/.openmates(-rust)
    <profile>/home/.config|.cache|.local/share|.local/state   XDG_* dirs
    <profile>/tmp     TMPDIR

The child environment is built from scratch (never inherited wholesale), so no
OPENMATES_PROFILE / OPENMATES_API_KEY / account-guard / keyring session-bus
variables leak from the caller. Only PATH (to locate node) plus explicit
``--pass-env`` names are inherited.
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

READ_FLOWS = ("whoami", "chats-list", "chats-show")
# Opt-in read variants: chats-show-cold runs an untimed `chats list` before every timed show
# (first open after a fresh list, instead of back-to-back shows).
EXTRA_READ_FLOWS = ("chats-show-cold",)
INFERENCE_FLOWS = ("send", "follow-up", "app-skill")
ALL_FLOWS = READ_FLOWS + EXTRA_READ_FLOWS + INFERENCE_FLOWS
DEFAULT_MESSAGE = "Reply with exactly one word: pong"
DEFAULT_FOLLOWUP = "Reply with exactly one word: ping"
DEFAULT_APP_SKILL = 'math calculate "sqrt(144)" --mode numeric'
# Pins the TS self-update check so no npm registry request is part of a sample.
DEFAULT_LATEST_VERSION_PIN = "0.0.0"


class IsolationError(ValueError):
    pass


@dataclass
class Arm:
    name: str  # "rust" | "typescript"
    command: list[str]  # e.g. ["/path/openmates"] or ["node", "/path/dist/cli.js"]
    profile: Path
    api_url: str
    app_url: str | None = None
    pass_env: list[str] = field(default_factory=list)
    latest_version_pin: str = DEFAULT_LATEST_VERSION_PIN

    @property
    def state_dir(self) -> Path:
        return self.profile / "state"

    @property
    def home(self) -> Path:
        return self.profile / "home"

    def prepare_dirs(self) -> None:
        for path in (self.profile, self.state_dir, self.home, self.profile / "tmp",
                     self.home / ".config", self.home / ".cache",
                     self.home / ".local" / "share", self.home / ".local" / "state"):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def env(self, inherited: dict | None = None) -> dict:
        source = os.environ if inherited is None else inherited
        env = {
            "PATH": source.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "TMPDIR": str(self.profile / "tmp"),
            "OPENMATES_STATE_DIR": str(self.state_dir),
            "OPENMATES_API_URL": self.api_url,
            "OPENMATES_CLI_LATEST_VERSION": self.latest_version_pin,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "CI": source.get("CI", ""),
        }
        if self.app_url:
            env["OPENMATES_APP_URL"] = self.app_url
        for name in self.pass_env:
            if name in source:
                env[name] = source[name]
        return {key: value for key, value in env.items() if value != ""}

    def argv(self, args: list[str]) -> list[str]:
        if self.name == "rust":
            return [*self.command, "--state-dir", str(self.state_dir), "--api-url", self.api_url, *args]
        return [*self.command, "--api-url", self.api_url, *args]


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_isolation(arms: list[Arm], real_home: Path) -> None:
    """Refuse shared/nested profiles and the real user's default CLI state."""
    rust, ts = (arm.profile.resolve() for arm in arms)
    for arm in arms:
        if not arm.profile.is_absolute():
            raise IsolationError(f"{arm.name} profile must be an absolute path")
    if rust == ts or _inside(rust, ts) or _inside(ts, rust):
        raise IsolationError("rust and typescript profiles must be separate, non-nested directories")
    forbidden = [real_home / ".openmates", real_home / ".openmates-rust"]
    for arm in arms:
        resolved = arm.profile.resolve()
        for path in forbidden:
            if _inside(resolved, path.resolve()) or resolved == real_home.resolve():
                raise IsolationError(f"{arm.name} profile must not be inside the real CLI state {path}")


def parse_command(text: str) -> list[str]:
    parts = shlex.split(text)
    if not parts:
        raise IsolationError("empty CLI command")
    # CLIs run with cwd = their profile root, so make existing relative paths absolute.
    return [str(Path(part).absolute()) if not Path(part).is_absolute() and ("/" in part) and Path(part).exists()
            else part for part in parts]


@dataclass
class Flow:
    name: str
    semantic: str  # human-readable argv with placeholders, for the report
    needs_chat: bool = False
    needs_inference: bool = False


FLOWS = {
    "whoami": Flow("whoami", "openmates whoami --json"),
    "chats-list": Flow("chats-list", "openmates chats list --limit 100 --json"),
    "chats-show": Flow("chats-show", "openmates chats show <chat-id> --json", needs_chat=True),
    "chats-show-cold": Flow("chats-show-cold", "openmates chats list (untimed); openmates chats show <chat-id> --json",
                            needs_chat=True),
    "send": Flow("send", "openmates chats new <message> --json", needs_inference=True),
    "follow-up": Flow("follow-up", "openmates chats send --chat <chat-id> <message> --json",
                      needs_chat=True, needs_inference=True),
    "app-skill": Flow("app-skill", "openmates apps <app> <skill> ... --json", needs_inference=True),
}


def flow_args(flow: str, chat_id: str | None = None, message: str = DEFAULT_MESSAGE,
              followup: str = DEFAULT_FOLLOWUP, app_skill: str = DEFAULT_APP_SKILL) -> list[str]:
    if flow == "whoami":
        return ["whoami", "--json"]
    if flow == "chats-list":
        return ["chats", "list", "--limit", "100", "--json"]
    if flow in ("chats-show", "chats-show-cold"):
        if not chat_id:
            raise ValueError("chats-show needs a chat id")
        return ["chats", "show", chat_id, "--json"]
    if flow == "send":
        return ["chats", "new", message, "--json"]
    if flow == "follow-up":
        if not chat_id:
            raise ValueError("follow-up needs a chat id")
        return ["chats", "send", "--chat", chat_id, followup, "--json"]
    if flow == "app-skill":
        return ["apps", *shlex.split(app_skill), "--json"]
    raise ValueError(f"unknown flow {flow}")


def parse_json_output(raw: bytes):
    """CLI --json stdout must be one JSON document; tolerate a trailing JSONL stream by taking the last line."""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
    return None


def error_code(value) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("error"), dict):
        code = value["error"].get("code")
        return str(code) if code else "error"
    if isinstance(value, dict) and value.get("success") is False:
        return "success_false"
    return None


def first_chat_id(listing) -> str | None:
    """First chat id from `chats list --json` ({"chats":[{"id":...}]} in both CLIs)."""
    rows = listing.get("chats") if isinstance(listing, dict) else listing
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                for key in ("id", "chat_id", "chatId"):
                    if isinstance(row.get(key), str) and row[key]:
                        return row[key]
    return None


def answered_model(value) -> str | None:
    """Assistant model name from `chats new/send --json` (modelName in both CLIs)."""
    if not isinstance(value, dict):
        return None
    for key in ("modelName", "model_name"):
        if isinstance(value.get(key), str) and value[key]:
            return value[key]
    return None


def created_chat_id(value) -> str | None:
    """Chat id from `chats new --json` (top-level chat_id/chatId or nested chat.id)."""
    if not isinstance(value, dict):
        return None
    for key in ("chat_id", "chatId"):
        if isinstance(value.get(key), str) and value[key]:
            return value[key]
    chat = value.get("chat")
    if isinstance(chat, dict):
        for key in ("id", "chat_id", "chatId"):
            if isinstance(chat.get(key), str) and chat[key]:
                return chat[key]
    return None
