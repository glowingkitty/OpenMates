#!/usr/bin/env python3
"""
Publish a newsletter issue from ``openmates-marketing/campaigns/<slug>/``
into the OpenMates repo as a committable set of files.

Why this script exists: ``openmates-marketing/`` is the authoring workspace
on the admin's dev machine. Prod doesn't have access to it, so before we can
send a newsletter from prod we must capture every piece of content the
dispatcher and SEO pages need as regular files inside this repo.

Outputs (committed to OpenMates):

    backend/newsletters/issues/<slug>.yml
        Email-level metadata: subject/subtitle/cta_text per language,
        category, body i18n key, video info, and ``sent_at`` (empty until
        broadcast — send_newsletter.py writes it after a successful send).

    frontend/packages/ui/src/demo_chats/data/<kind>_<slug>.ts
        ``DemoChat`` object with ``chat_id: "<kind>-<slug>"`` and
        ``demo_chat_category: "news"`` (announcements) or ``"features"``
        (tips). Video metadata flows into ``metadata.video_*`` so the chat
        header renders the video just like intro chats do.

    frontend/packages/ui/src/i18n/sources/demo_chats/<kind>_<slug>.yml
        Translation keys (title, summary, message body, follow-ups) with
        EN + DE populated from the marketing MD. Other languages left empty
        for the translation build to fill in later.

The script also patches ``newsletterChatStore.ts`` to import + register the
new chat inside the BEGIN/END markers so ``getPublicChatById`` picks it up
for chat-id deep links.

Optional ``--test-to <email>`` dispatches a test send through the dev Brevo
account using the just-generated files, so the admin can inspect the email
and the landing page before committing.

Usage:
    docker exec -it api python /app/backend/scripts/publish_newsletter.py \\
        --issue-dir /openmates-marketing/campaigns/<slug>/

    docker exec -it api python /app/backend/scripts/publish_newsletter.py \\
        --issue-dir /openmates-marketing/campaigns/<slug>/ \\
        --test-to testing@openmates.org
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

sys.path.insert(0, "/app/backend")

from backend.core.api.app.utils.log_filters import SensitiveDataFilter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

# Repo-relative paths written by this script. The script runs inside the
# ``api`` container where the OpenMates repo is bind-mounted at /app.
REPO_ROOT = Path("/app")
ISSUES_DIR = REPO_ROOT / "backend" / "newsletters" / "issues"
DATA_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "demo_chats" / "data"
I18N_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "demo_chats"
STORE_FILE = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "demo_chats" / "newsletterChatStore.ts"

# category (in meta.yml / newsletter_subscribers.categories) → URL kind + demo_chat_category
CATEGORY_TO_KIND: Dict[str, Tuple[str, str]] = {
    "updates_and_announcements": ("announcements", "news"),
    "tips_and_tricks": ("tips", "features"),
}

FRONTMATTER_DELIMITERS = ("---", "-----")
SUPPORTED_LANGS = ("en", "de")
ALL_LANG_CODES = (
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he",
)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Strip optional YAML frontmatter — same convention as the MD renderer."""
    lines = text.splitlines()
    if not lines:
        return {}, text
    delim = lines[0].strip()
    if delim not in FRONTMATTER_DELIMITERS:
        return {}, text
    close_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == delim:
            close_idx = idx
            break
    if close_idx is None:
        return {}, text
    parsed = yaml.safe_load("\n".join(lines[1:close_idx])) or {}
    if not isinstance(parsed, dict):
        raise ValueError("Frontmatter must be a YAML mapping")
    body = "\n".join(lines[close_idx + 1:]).strip()
    return parsed, body


def _strip_video_marker(body: str) -> str:
    """Drop any ``[video]`` on its own line — the demo chat renders the video
    in the header via ``metadata.video_*`` fields, so a duplicate marker in
    the body would render a literal ``[video]`` string in the chat UI."""
    return re.sub(r"^\s*\[video\]\s*$", "", body, flags=re.MULTILINE).strip()


def _camel(slug: str) -> str:
    """``april-2026-update`` → ``april2026Update``."""
    parts = re.split(r"[-_]+", slug)
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _snake(slug: str) -> str:
    """``april-2026-update`` → ``april_2026_update``."""
    return re.sub(r"-+", "_", slug)


def load_issue_inputs(issue_dir: Path) -> Dict[str, Any]:
    """Read meta.yml + newsletter_{EN,DE}.md from a marketing issue folder."""
    meta_path = issue_dir / "meta.yml"
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.yml missing in {issue_dir}")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

    slug = meta.get("slug")
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(f"meta.yml slug invalid: {slug!r}")

    category = meta.get("category")
    if category not in CATEGORY_TO_KIND:
        raise ValueError(
            f"meta.yml category must be one of {list(CATEGORY_TO_KIND)} (got {category!r})"
        )

    bodies: Dict[str, Dict[str, Any]] = {}
    for lang in SUPPORTED_LANGS:
        body_path = issue_dir / f"newsletter_{lang.upper()}.md"
        if not body_path.exists():
            raise FileNotFoundError(f"Missing body file: {body_path}")
        raw = body_path.read_text(encoding="utf-8")
        if not raw.strip():
            raise ValueError(f"Empty body file: {body_path}")
        front, body = _split_frontmatter(raw)
        subject = front.get("subject") or front.get("title")
        if not subject:
            raise ValueError(f"{body_path.name} frontmatter must set `subject`")
        bodies[lang] = {
            "subject": str(subject).strip(),
            "subtitle": (front.get("subtitle") or "").strip() or None,
            "cta_text": (front.get("cta_text") or "").strip() or None,
            "raw_body": body,
            "chat_body": _strip_video_marker(body),
        }

    return {"meta": meta, "slug": slug, "category": category, "bodies": bodies}


def write_issue_manifest(inputs: Dict[str, Any]) -> Path:
    """Write backend/newsletters/issues/<slug>.yml — the dispatcher's source."""
    slug = inputs["slug"]
    meta = inputs["meta"]
    bodies = inputs["bodies"]
    kind, demo_cat = CATEGORY_TO_KIND[inputs["category"]]
    snake_slug = _snake(slug)
    i18n_key_root = f"demo_chats.{kind}_{snake_slug}"

    manifest = {
        "slug": slug,
        "kind": kind,  # "announcements" | "tips"
        "category": inputs["category"],
        "demo_chat_category": demo_cat,
        "chat_id": f"{kind}-{slug}",
        "subject": {lang: bodies[lang]["subject"] for lang in SUPPORTED_LANGS},
        "subtitle": {lang: bodies[lang]["subtitle"] for lang in SUPPORTED_LANGS},
        "cta_url": meta.get("cta_url"),
        "cta_text": {lang: bodies[lang]["cta_text"] for lang in SUPPORTED_LANGS},
        "body_i18n_key": f"{i18n_key_root}.message",
        "video": {
            "mp4_url": meta.get("video_mp4_url"),
            "hls_url": meta.get("video_hls_url"),
            "thumbnail_url": meta.get("video_thumbnail_url"),
            "start_time": meta.get("video_start_time"),
        } if meta.get("video_mp4_url") or meta.get("video_hls_url") else None,
        # Empty until send_newsletter.py broadcasts this issue. Prevents
        # accidental double-sends without an explicit --resend-confirm flag.
        "sent_at": None,
    }

    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    path = ISSUES_DIR / f"{slug}.yml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info(f"Wrote manifest: {path}")
    return path


def write_demo_chat_ts(inputs: Dict[str, Any]) -> Path:
    """Emit the TypeScript ``DemoChat`` file used by the frontend."""
    slug = inputs["slug"]
    meta = inputs["meta"]
    kind, _ = CATEGORY_TO_KIND[inputs["category"]]
    snake_slug = _snake(slug)
    camel_slug = _camel(slug)
    i18n_key_root = f"demo_chats.{kind}_{snake_slug}"
    export_name = f"{kind}{camel_slug[0].upper()}{camel_slug[1:]}Chat"

    video_lines = []
    if meta.get("video_hls_url"):
        video_lines.append(f'    video_hls_url: "{meta["video_hls_url"]}",')
    if meta.get("video_mp4_url"):
        video_lines.append(f'    video_mp4_url: "{meta["video_mp4_url"]}",')
    if meta.get("video_thumbnail_url"):
        video_lines.append(f'    video_thumbnail_url: "{meta["video_thumbnail_url"]}",')
    if meta.get("video_start_time") is not None:
        video_lines.append(f'    video_start_time: {int(meta["video_start_time"])},')
    video_block = "\n".join(video_lines) if video_lines else ""

    content = f'''import type {{ DemoChat }} from "../types";

/**
 * Newsletter demo chat — {slug}
 * Kind: {kind} (derived from meta.yml category "{inputs["category"]}")
 * Generated by backend/scripts/publish_newsletter.py — edits will be
 * overwritten next time the publisher runs on this slug.
 */
export const {export_name}: DemoChat = {{
  chat_id: "{kind}-{slug}",
  slug: "{slug}",
  title: "{i18n_key_root}.title",
  description: "{i18n_key_root}.description",
  keywords: [
    "OpenMates",
    "newsletter",
    "{kind}",
  ],
  messages: [
    {{
      id: "{kind}-{slug}-1",
      role: "assistant",
      content: "{i18n_key_root}.message",
      timestamp: new Date().toISOString(),
    }},
  ],
  metadata: {{
    category: "openmates_official",
    icon_names: {"['megaphone', 'sparkles']" if kind == "announcements" else "['lightbulb', 'sparkles']"},
    featured: false,
    order: 100,
    lastUpdated: new Date().toISOString(),
{video_block}
  }},
}};
'''

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{kind}_{snake_slug}.ts"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Wrote DemoChat: {path}")
    return path


def _yaml_scalar(value: Optional[str]) -> str:
    """Hand-roll a YAML scalar we can safely inline next to a key.

    Uses single-quoted style for one-liners (escaping internal '') and a
    literal-block scalar (``|-``) for multi-line content. Avoids
    ``yaml.safe_dump`` because it sometimes appends a ``...`` document-end
    marker that corrupts the surrounding multi-key document.
    """
    if value is None or value == "":
        return "''"
    if "\n" in value:
        indented = "\n".join("    " + line for line in value.splitlines())
        return "|-\n" + indented
    return "'" + value.replace("'", "''") + "'"


def write_i18n_yml(inputs: Dict[str, Any]) -> Path:
    """Write the i18n source file with EN + DE populated for every key.

    We intentionally leave the other 19 locales empty — the existing
    translation build picks them up on the next pass and translations can be
    backfilled without regenerating this file.
    """
    slug = inputs["slug"]
    bodies = inputs["bodies"]
    kind, _ = CATEGORY_TO_KIND[inputs["category"]]
    snake_slug = _snake(slug)

    def _block(key_ctx: str, en_val: str, de_val: str) -> str:
        lines = [f"{key_ctx}:"]
        lines.append(f"  context: {_yaml_scalar(f'Newsletter {kind}/{slug} — {key_ctx}')}")
        for code in ALL_LANG_CODES:
            if code == "en":
                lines.append(f"  en: {_yaml_scalar(en_val)}")
            elif code == "de":
                lines.append(f"  de: {_yaml_scalar(de_val)}")
            else:
                lines.append(f"  {code}: ''")
        lines.append("  verified_by_human: []")
        return "\n".join(lines)

    title_block = _block("title", bodies["en"]["subject"], bodies["de"]["subject"])
    description_block = _block(
        "description",
        bodies["en"]["subtitle"] or bodies["en"]["subject"],
        bodies["de"]["subtitle"] or bodies["de"]["subject"],
    )
    message_block = _block("message", bodies["en"]["chat_body"], bodies["de"]["chat_body"])

    content = (
        f"# Newsletter {kind}/{slug}\n"
        f"# Auto-generated by backend/scripts/publish_newsletter.py.\n"
        f"# EN + DE are canonical; other languages are filled on the next translation pass.\n\n"
        f"{title_block}\n"
        f"{description_block}\n"
        f"{message_block}\n"
    )

    I18N_DIR.mkdir(parents=True, exist_ok=True)
    path = I18N_DIR / f"{kind}_{snake_slug}.yml"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Wrote i18n source: {path}")
    return path


def register_in_store(inputs: Dict[str, Any]) -> None:
    """Patch newsletterChatStore.ts to import + include this issue's chat.

    Idempotent: running the publisher twice on the same slug leaves a single
    import + a single registration (the second run overwrites its own
    lines between the BEGIN/END markers).
    """
    slug = inputs["slug"]
    kind, _ = CATEGORY_TO_KIND[inputs["category"]]
    snake_slug = _snake(slug)
    camel_slug = _camel(slug)
    export_name = f"{kind}{camel_slug[0].upper()}{camel_slug[1:]}Chat"

    text = STORE_FILE.read_text(encoding="utf-8")

    # Imports block
    imports_block = _replace_between_markers(
        text,
        "// BEGIN_NEWSLETTER_IMPORTS",
        "// END_NEWSLETTER_IMPORTS",
        current_import_line=f'import {{ {export_name} }} from "./data/{kind}_{snake_slug}";',
    )

    # Registration block (inside the array literal)
    registrations_block = _replace_between_markers(
        imports_block,
        "// BEGIN_NEWSLETTER_REGISTRATIONS",
        "// END_NEWSLETTER_REGISTRATIONS",
        current_import_line=f"  {export_name},",
    )

    STORE_FILE.write_text(registrations_block, encoding="utf-8")
    logger.info(f"Registered {export_name} in newsletterChatStore.ts")


def _replace_between_markers(
    text: str, begin_marker: str, end_marker: str, current_import_line: str
) -> str:
    """Replace/insert one line between BEGIN/END markers, preserving others."""
    pattern = re.compile(
        rf"({re.escape(begin_marker)}\n)(.*?)(\s*{re.escape(end_marker)})",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Markers not found in newsletterChatStore.ts: {begin_marker}")
    prefix, existing, suffix = match.group(1), match.group(2), match.group(3)

    # Keep lines that are not overwriting the same symbol.
    symbol = current_import_line.strip().rstrip(",")
    kept = [line for line in existing.splitlines() if line.strip() and symbol not in line]
    kept.append(current_import_line)

    new_section = prefix + "\n".join(kept) + "\n" + suffix.lstrip()
    return text[:match.start()] + new_section + text[match.end():]


async def send_test_email(
    slug: str,
    recipient: str,
    manifest_path: Path,
) -> bool:
    """Send one test email to the admin using the just-generated manifest."""
    # Lazy-import so the publisher still works when email infra isn't ready.
    from backend.scripts.send_newsletter import (  # noqa: E402
        build_video_thumbnail_attachment_from_manifest,  # noqa: F401 (may not exist yet)
    )
    raise NotImplementedError(
        "Test send integration lives inside send_newsletter.py — call it with --test-to instead."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a newsletter issue into the OpenMates repo")
    parser.add_argument(
        "--issue-dir",
        type=str,
        required=True,
        help="Path to openmates-marketing/campaigns/<slug>/",
    )
    parser.add_argument(
        "--test-to",
        type=str,
        default=None,
        help=(
            "After publishing, send a test email via dev Brevo to this address. "
            "Equivalent to running send_newsletter.py --slug <slug> --test-to <email>."
        ),
    )
    args = parser.parse_args()

    issue_dir = Path(args.issue_dir).expanduser().resolve()
    if not issue_dir.is_dir():
        logger.error(f"Issue directory not found: {issue_dir}")
        return 2

    inputs = load_issue_inputs(issue_dir)
    slug = inputs["slug"]
    kind, _ = CATEGORY_TO_KIND[inputs["category"]]

    write_issue_manifest(inputs)
    write_demo_chat_ts(inputs)
    write_i18n_yml(inputs)
    register_in_store(inputs)

    logger.info("=" * 72)
    logger.info(f"Published {kind}-{slug}")
    logger.info("Next: review the diff, commit, `sessions.py deploy` to auto-deploy dev.")
    logger.info(f"Dev URL (after deploy): https://app.dev.openmates.org/{kind}/{slug}")
    logger.info(f"Prod URL (after merge to main): https://openmates.org/{kind}/{slug}")
    logger.info("=" * 72)

    if args.test_to:
        logger.info(f"Dispatching test email to {_mask_email(args.test_to)}...")
        # We shell out to send_newsletter.py via its Python API to reuse every
        # guardrail (TTY check is skipped for --test-to since the test-send
        # path never broadcasts).
        from backend.scripts import send_newsletter  # noqa: E402
        rc = asyncio.run(send_newsletter.run(argparse.Namespace(
            slug=slug,
            issue_dir=None,
            lang="en",
            dry_run=False,
            render_to=None,
            test_to=args.test_to,
            confirm_send=False,
            limit=None,
            resend_confirm=False,
        )))
        logger.info(f"Test send finished with exit code {rc}")
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
