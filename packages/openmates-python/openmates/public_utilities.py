"""Pure, credential-free helpers shared with the npm and Rust SDK utilities."""
from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SUPPORT_URL = "https://app.openmates.org/#settings/support"
ASSISTANT_FEEDBACK_THANKS = "Thanks for the feedback!"
ASSISTANT_FEEDBACK_REPORT_TITLE = "Assistant response quality bad:"
_FALLBACK_APP_URL = "https://app.openmates.org"
_PRERELEASE = re.compile(r"-(alpha|beta|rc)(\.|\d|$)")
_EXTENSIONS = {
    "javascript": "js", "typescript": "ts", "python": "py", "ruby": "rb", "rust": "rs",
    "golang": "go", "go": "go", "java": "java", "kotlin": "kt", "swift": "swift",
    "csharp": "cs", "c#": "cs", "cpp": "cpp", "c++": "cpp", "c": "c", "html": "html",
    "css": "css", "scss": "scss", "json": "json", "yaml": "yml", "yml": "yml",
    "xml": "xml", "sql": "sql", "shell": "sh", "bash": "sh", "zsh": "sh",
    "powershell": "ps1", "dockerfile": "Dockerfile", "docker": "Dockerfile",
    "markdown": "md", "md": "md", "toml": "toml", "ini": "ini", "lua": "lua", "r": "r",
    "php": "php", "perl": "pl", "scala": "scala", "svelte": "svelte", "vue": "vue",
    "jsx": "jsx", "tsx": "tsx", "": "txt",
}
_LABELS = {
    "likely_ai_generated": "Likely AI-generated",
    "possibly_ai_generated": "Possibly AI-generated",
    "likely_not_ai_generated": "Likely not AI-generated",
    "unavailable": "Detection unavailable",
}


def render_support_info() -> str:
    return (
        "Support OpenMates development:\n  " + SUPPORT_URL
        + "\n\nFinancial support is voluntary and helps keep OpenMates maintained."
    )


def default_clone_branch_for_version(version: str) -> str | None:
    return "dev" if _PRERELEASE.search(version) else None


def derive_app_url(api_url: str) -> str:
    """Explicit-option derivation only; no environment or installed-server lookup."""
    try:
        parts = urlsplit(api_url)
        host = parts.hostname
    except ValueError:
        return _FALLBACK_APP_URL
    if not parts.scheme or not host:
        return _FALLBACK_APP_URL
    if host == "api.dev.openmates.org":
        return "https://app.dev.openmates.org"
    if host == "api.openmates.org":
        return _FALLBACK_APP_URL
    if host in ("localhost", "127.0.0.1", "::1"):
        return "http://localhost:5173"
    netloc = parts.netloc
    if host.startswith("api."):
        netloc = netloc.replace(host, "app." + host[4:], 1)
    return urlunsplit((parts.scheme, netloc, "", "", "")).rstrip("/")


def get_ext_for_lang(language: str) -> str:
    lower = language.lower()
    return _EXTENSIONS.get(lower, lower)


def build_assistant_feedback_decision(rating: Any) -> dict[str, Any]:
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValueError("Rating must be an integer from 1 to 5.")
    low = rating <= 3
    return {
        "rating": rating,
        "action": "report_issue" if low else "thanks",
        "message": ASSISTANT_FEEDBACK_THANKS,
        "report_title": ASSISTANT_FEEDBACK_REPORT_TITLE if low else None,
    }


def classify_images_ai_detection(score: float | None) -> str:
    if score is None or isinstance(score, bool) or not math.isfinite(score):
        return "unavailable"
    if score > 0.7:
        return "likely_ai_generated"
    if score > 0.4:
        return "possibly_ai_generated"
    return "likely_not_ai_generated"


def format_images_ai_detection_label(classification: str) -> str:
    return _LABELS[classification]


def build_images_ai_detection_summary(upload: dict[str, Any], file_path: str) -> dict[str, Any]:
    detection = upload.get("ai_detection")
    detection = detection if isinstance(detection, dict) else None
    status = (detection or {}).get("status") or ("success" if detection is not None else "unavailable")
    score = (detection or {}).get("ai_generated") if status == "success" else None
    classification = classify_images_ai_detection(score if isinstance(score, (int, float)) else None)
    basename = re.split(r"[\\/]", file_path)[-1]
    return {
        "file": file_path,
        "filename": upload.get("filename") or basename,
        "content_type": upload.get("content_type"),
        "embed_id": upload.get("embed_id"),
        "deduplicated": upload.get("deduplicated"),
        "stored": True,
        "status": status,
        "provider": (detection or {}).get("provider"),
        "ai_generated": score if classification != "unavailable" else None,
        "classification": classification,
        "label": _LABELS[classification],
        "error": (detection or {}).get("error"),
    }
