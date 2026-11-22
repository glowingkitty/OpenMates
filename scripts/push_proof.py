"""Screenshots, videos and output files on the ✅/❓ Discord pushes of scripts/agent_question.py, and the proof check.

Attachments (``--attach PATH``, repeatable): screenshots (.png .jpg .jpeg .webp .gif) and videos
(.mp4 .webm .mov) go into the push as real Discord files (webhook multipart upload, at most
MAX_FILES per message and MESSAGE_BYTES in total, Discord's limit for webhooks). A screenshot over
IMAGE_MAX_BYTES or over the remaining budget is re-encoded as JPEG and scaled down (Pillow) until it
fits. A video that does not fit is re-encoded once with ffmpeg (H.264, at most 1280 px wide); when it
still does not fit, or ffmpeg fails, the original goes to the private 7-day proof storage (the
AI test users video bucket, signed link valid as long as the object) and the push carries that link.
``--link URL`` adds an existing proof link; only presigned links to our own private buckets are
accepted (agent_question.own_storage_link). The short-text limit covers the text only; attachments
and links go out on top of it.

Output files (owner, 22 Nov 2026): what a chat produced for the owner to download (FILE_SUFFIXES:
archives, embroidery machine files, PDF, SVG, 3D models, CSV) are attached as they are, so Discord
offers them as downloads. One that does not fit the message goes to the same private 7-day storage
and the push carries its link. Output files are not visual proof (see the proof check below).

Privacy: proof can show user-like data. It goes only to the push webhook (the owner's private
channel) and the private bucket, never into the repository; compressed copies live in a temporary
directory that is removed after the push. Paths under ``.auth``, ``ci-private`` or ``.env*`` are
refused.

Proof check (owner, 21 Nov 2026): a push needs a screenshot or video only when the chat has
something visual to show:
  * a session of the chat changed UI files (UI_SUFFIXES anywhere outside test folders, Swift view
    files, Apple asset catalogs, email templates), or
  * a session of the chat ran an end-to-end or visual CI job (VISUAL_CI_MODES) that finished; its
    screenshots or video come from that run.
Everything else (research, backend work, security checks, docs, tooling) is never asked for proof
and never refused for lacking it; the push wording plays no part. A push that needs proof and has
none is refused (exit 1) unless ``--no-proof "<why>"`` is given, which sends it with a loud
"No screenshot or video" line so the owner sees what is missing.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
# Output files the owner downloads; stored as application/zip, application/pdf or octet-stream.
FILE_SUFFIXES = {".zip", ".pes", ".dst", ".exp", ".jef", ".vp3", ".pdf", ".svg", ".stl", ".3mf", ".csv"}
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
                 ".zip": "application/zip", ".pdf": "application/pdf"}
MAX_FILES = 10  # Discord: attachments per message
MESSAGE_BYTES = 9 * 1024 * 1024 + 512 * 1024  # under Discord's 10 MiB webhook upload limit, with room for the form
IMAGE_MAX_BYTES = 4 * 1024 * 1024  # a screenshot above this is re-encoded even when it would fit
IMAGE_SIDES = (2560, 1920, 1440, 1080)
JPEG_QUALITIES = (85, 70, 55)
VIDEO_ENCODE_TIMEOUT = 300
PRIVATE_PARTS = {".auth", "ci-private"}
STORAGE_PREFIX = "agent-pushes"

# Proof check: what counts as "something visual to show".
UI_SUFFIXES = {".svelte", ".css", ".scss", ".mjml"}
SWIFT_VIEW_MARKERS = ("/Views/", "View.swift", "Screen.swift")
EMAIL_TEMPLATE_DIR = "templates/email"
TEST_PARTS = {"tests", "__tests__", "test", "OpenMatesTests", "OpenMatesUITests"}
VISUAL_CI_MODES = ("e2e", "component", "visual-smoke", "apple-ui")
FINISHED_STATES = ("success", "failure")
CI_QUEUE = Path("logs") / "ci-coordinator" / "queue.sqlite3"


class ProofError(RuntimeError):
    """An attachment or link that cannot be sent (missing, private, unsupported, upload failed)."""


@dataclass
class Prepared:
    """What goes out with the push: files for the multipart upload, and link lines."""
    files: list[tuple[str, bytes]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (label, url)
    notes: list[str] = field(default_factory=list)  # what was compressed or uploaded, for the chat

    @property
    def empty(self) -> bool:
        return not self.files and not self.links

    def link_lines(self) -> list[str]:
        return [f"{label}: <{url}>" for label, url in self.links]


# --- proof check ----------------------------------------------------------------------------------

def is_ui_file(path: str) -> bool:
    """True for a file whose change is visible: UI styles/components, Swift views, assets, email templates."""
    parts = PurePosixPath(path).parts
    if TEST_PARTS.intersection(parts) or path.endswith((".spec.ts", ".test.ts", "Tests.swift")):
        return False
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in UI_SUFFIXES:
        return True
    if path.startswith("apple/"):
        if ".xcassets/" in path:
            return True
        return suffix == ".swift" and any(marker in f"/{path}" for marker in SWIFT_VIEW_MARKERS)
    return EMAIL_TEMPLATE_DIR in path and suffix in {".html", ".mjml"}


def chat_sessions(root: Path, chat_id: str) -> dict[str, dict]:
    """sessions.py sessions (key -> record) that belong to this chat."""
    if not chat_id:
        return {}
    try:
        data = json.loads((root / ".claude" / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: info for key, info in (data.get("sessions") or {}).items()
            if (info.get("agent_task_id") or info.get("codex_task_id")) == chat_id}


def visual_ci_jobs(root: Path, owners: list[str]) -> list[tuple[str, str]]:
    """(mode, specs) of finished visual CI jobs these sessions own; [] when the queue is unreadable."""
    path = root / CI_QUEUE
    if not owners or not path.is_file():
        return []
    marks = ",".join("?" * len(owners))
    query = (f"select mode, specs from jobs where owner in ({marks}) and mode in "
             f"({','.join('?' * len(VISUAL_CI_MODES))}) and state in ({','.join('?' * len(FINISHED_STATES))})")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as db:
            return [(str(m), str(s)) for m, s in db.execute(query, (*owners, *VISUAL_CI_MODES, *FINISHED_STATES))]
    except sqlite3.Error:
        return []


def proof_reasons(root: Path, chat_id: str) -> list[str]:
    """Why this chat has something visual to show (empty: no proof needed). See the module docstring."""
    sessions = chat_sessions(root, chat_id)
    reasons: list[str] = []
    ui_files = sorted({f for info in sessions.values() for f in info.get("modified_files") or [] if is_ui_file(f)})
    if ui_files:
        more = f" and {len(ui_files) - 3} more" if len(ui_files) > 3 else ""
        reasons.append("changed UI files (" + ", ".join(PurePosixPath(f).name for f in ui_files[:3]) + more + ")")
    jobs = visual_ci_jobs(root, list(sessions))
    if jobs:
        modes = sorted({mode for mode, _ in jobs})
        reasons.append(f"ran {len(jobs)} end-to-end or visual CI job(s) ({', '.join(modes)})")
    return reasons


def refusal(reasons: list[str]) -> str:
    return ("this push needs a screenshot or video: the chat " + " and ".join(reasons) + ". Attach the proof "
            "with --attach <png/jpg/webm/mp4> (repeatable; CI screenshots and videos are in the run's folder "
            "under test-results/ci-runs/) or --link <signed proof link>; if there truly is nothing to show, "
            "pass --no-proof \"<why>\" and the push says so")


# --- attachments ----------------------------------------------------------------------------------

def check_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if any(part in PRIVATE_PARTS or part.startswith(".env") for part in path.parts):
        raise ProofError(f"{path.name}: private paths (.auth, ci-private, .env) are never attached")
    if not path.is_file():
        raise ProofError(f"{raw}: no such file")
    if path.suffix.lower() not in IMAGE_SUFFIXES | VIDEO_SUFFIXES | FILE_SUFFIXES:
        raise ProofError(f"{path.name}: only screenshots ({', '.join(sorted(IMAGE_SUFFIXES))}), videos "
                         f"({', '.join(sorted(VIDEO_SUFFIXES))}) and output files "
                         f"({', '.join(sorted(FILE_SUFFIXES))}) can be attached")
    return path


def is_visual(raw: str) -> bool:
    """True for a screenshot or video, the attachments that count as proof."""
    return Path(raw).suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES


def unique_name(name: str, taken: set[str]) -> str:
    """A filename safe for the multipart form, distinct from the ones already attached."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "proof"
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{stem}-{n}{suffix}", n + 1
    taken.add(candidate)
    return candidate


def compress_image(content: bytes, budget: int) -> bytes | None:
    """JPEG re-encodes at decreasing size/quality until one is at most ``budget`` bytes; None if none is."""
    from PIL import Image  # dev host dependency; only needed when a screenshot is too large

    with Image.open(io.BytesIO(content)) as image:
        image.load()
        rgb = image.convert("RGB")
    for side in (max(rgb.size), *IMAGE_SIDES):
        scaled = rgb.copy()
        scaled.thumbnail((side, side))
        for quality in JPEG_QUALITIES:
            out = io.BytesIO()
            scaled.save(out, format="JPEG", quality=quality, optimize=True)
            if out.tell() <= budget:
                return out.getvalue()
    return None


def compress_video(source: Path, work: Path,
                   run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bytes | None:
    """One bounded ffmpeg re-encode (H.264, at most 1280 px wide, low priority); None when it fails."""
    if not shutil.which("ffmpeg"):
        return None
    target = work / f"{source.stem}-small.mp4"
    command = ["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf",
               "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
               "-threads", "2", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(target)]
    try:
        done = run(command, capture_output=True, text=True, timeout=VIDEO_ENCODE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return target.read_bytes() if done.returncode == 0 and target.is_file() else None


def upload_to_storage(path: Path, chat_id: str) -> str:
    """Upload one file to the private 7-day proof bucket; returns its signed link."""
    import ai_test_users_video as videos

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    key = f"{STORAGE_PREFIX}/{videos.KEY_PART.sub('_', chat_id or 'chat')}/{digest}-{videos.KEY_PART.sub('_', path.name)}"
    try:
        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return videos.upload(path, key, content_type=content_type)["url"]
    except (RuntimeError, OSError, ValueError) as error:
        raise ProofError(f"{path.name}: upload to the private proof storage failed ({error})") from error


def prepare(paths: list[str], links: list[str], chat_id: str, work: Path, *,
            own_link: Callable[[str], bool], uploader: Callable[[Path, str], str] = upload_to_storage,
            video_compressor: Callable[[Path, Path], bytes | None] = compress_video) -> Prepared:
    """Check, compress or upload every attachment so the push fits Discord's limits (module docstring)."""
    prepared = Prepared()
    for url in links:
        if not own_link(url):
            raise ProofError("--link accepts only signed links to our private proof storage (openmates-* buckets)")
        prepared.links.append(("Proof", url))
    checked = [check_path(raw) for raw in paths]
    images = [p for p in checked if p.suffix.lower() in IMAGE_SUFFIXES]
    videos = [p for p in checked if p.suffix.lower() in VIDEO_SUFFIXES]
    outputs = [p for p in checked if p.suffix.lower() in FILE_SUFFIXES]
    budget, taken = MESSAGE_BYTES, set()

    def attach(name: str, content: bytes) -> bool:
        nonlocal budget
        if len(prepared.files) >= MAX_FILES or len(content) > budget:
            return False
        prepared.files.append((unique_name(name, taken), content))
        budget -= len(content)
        return True

    def to_link(path: Path, why: str) -> None:
        prepared.links.append((path.name, uploader(path, chat_id)))
        prepared.notes.append(f"{path.name}: {why}, sent as a 7-day private link")

    for path in images:
        content = path.read_bytes()
        if len(content) <= min(IMAGE_MAX_BYTES, budget) and attach(path.name, content):
            continue
        smaller = None if path.suffix.lower() == ".gif" else compress_image(content, min(IMAGE_MAX_BYTES, budget))
        if smaller is not None and attach(f"{path.stem}.jpg", smaller):
            prepared.notes.append(f"{path.name}: compressed from {len(content)} to {len(smaller)} bytes")
        else:
            to_link(path, "too large to attach")
    for path in videos:
        content = path.read_bytes()
        if attach(path.name, content):
            continue
        smaller = video_compressor(path, work) if len(prepared.files) < MAX_FILES else None
        if smaller is not None and attach(f"{path.stem}.mp4", smaller):
            prepared.notes.append(f"{path.name}: re-encoded from {len(content)} to {len(smaller)} bytes")
        else:
            to_link(path, "over Discord's upload limit")
    for path in outputs:
        if not attach(path.name, path.read_bytes()):
            to_link(path, "over Discord's upload limit")
    return prepared


def temporary_workdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="push-proof-")
