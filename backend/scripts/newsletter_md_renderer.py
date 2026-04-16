"""
Renders a newsletter issue (frontmatter + markdown body) into an HTML fragment
ready to be injected into the `newsletter_content` slot of `newsletter.mjml`.

Design: each newsletter issue lives in its own directory (typically under
`openmates-marketing/campaigns/<issue-slug>/`) with per-language body files
(`newsletter_EN.md`, `newsletter_DE.md`) and a shared `meta.yml`. The meta
file holds non-translatable fields (slug, category, video_id, cta_url,
thumbnail path); the body markdown holds a small YAML frontmatter block for
translatable fields (subject, subtitle, cta_text) plus the actual content.

Custom markers supported in the markdown body:
- `[video]` on its own line → clickable thumbnail linked to the newsletter
  landing page (openmates.org/newsletter/<slug>). The thumbnail is passed in
  as an inline CID attachment (no third-party image hosts).

We intentionally do NOT embed YouTube/Vimeo iframes — most email clients
block them, and inline iframes would also let the video host track opens.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from markdown_it import MarkdownIt

logger = logging.getLogger(__name__)

VIDEO_PLACEHOLDER_MARKER = "[video]"
FRONTMATTER_DELIMITERS = ("---", "-----")
SUPPORTED_LANGS = ("en", "de")

# Newsletter category IDs that gate sends (to be honored by send script once
# per-category subscriber preferences land in Part B).
VALID_CATEGORIES = {
    "updates_and_announcements",
    "tips_and_tricks",
    "daily_inspirations",
}

VIDEO_CID = "newsletter-video-thumbnail@openmates"


@dataclass
class IssueMeta:
    """Non-translatable issue metadata loaded from meta.yml."""

    slug: str
    category: str
    cta_url: Optional[str] = None
    video_id: Optional[str] = None
    video_thumbnail_path: Optional[Path] = None
    show_social_media: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalizedIssue:
    """Per-language rendered output for one newsletter issue."""

    lang: str
    subject: str
    subtitle: Optional[str]
    cta_text: Optional[str]
    html_body: str
    has_video: bool


def load_issue_meta(issue_dir: Path) -> IssueMeta:
    """Load issue-level meta.yml (slug, category, CTA URL, video info)."""
    meta_path = issue_dir / "meta.yml"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"Newsletter issue is missing meta.yml: {meta_path}. "
            f"See backend/scripts/newsletter_md_renderer.py docstring for the expected schema."
        )

    raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

    slug = raw.get("slug")
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(
            f"meta.yml 'slug' is required and must be lowercase alphanumeric with dashes (got {slug!r})"
        )

    category = raw.get("category")
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"meta.yml 'category' must be one of {sorted(VALID_CATEGORIES)} (got {category!r})"
        )

    thumb_raw = raw.get("video_thumbnail")
    thumb_path: Optional[Path] = None
    if thumb_raw:
        thumb_path = (issue_dir / thumb_raw).resolve()
        if not thumb_path.exists():
            raise FileNotFoundError(f"meta.yml references missing thumbnail: {thumb_path}")

    return IssueMeta(
        slug=slug,
        category=category,
        cta_url=raw.get("cta_url"),
        video_id=raw.get("video_id"),
        video_thumbnail_path=thumb_path,
        show_social_media=bool(raw.get("show_social_media", False)),
        raw=raw,
    )


def _split_frontmatter(markdown_text: str) -> Tuple[Dict[str, Any], str]:
    """Strip optional YAML frontmatter from the top of the markdown file.

    Accepts both the standard ``---`` delimiters and the ``-----`` variant
    used in the existing April 2026 newsletter draft.
    """
    lines = markdown_text.splitlines()
    if not lines:
        return {}, markdown_text

    first_line = lines[0].strip()
    if first_line not in FRONTMATTER_DELIMITERS:
        return {}, markdown_text

    # Find the closing delimiter (same token as the opener).
    closing_idx: Optional[int] = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == first_line:
            closing_idx = idx
            break

    if closing_idx is None:
        # No closing delimiter → treat the whole file as body.
        return {}, markdown_text

    frontmatter_raw = "\n".join(lines[1:closing_idx])
    body = "\n".join(lines[closing_idx + 1:])

    try:
        parsed = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping, got {type(parsed).__name__}")

    return parsed, body


def _video_block_html(
    landing_url: str,
    thumbnail_cid: str,
    alt_text: str,
) -> str:
    """Render the clickable video thumbnail as a CID-referenced inline image.

    The thumbnail is wrapped in an anchor pointing to the newsletter landing
    page, where the actual video player lives. We use a CID attachment (via
    ``cid:...``) so the image travels with the email itself — no third-party
    image host, no tracker, and it renders even with external-image blocking.

    All interpolated values are HTML-attribute-escaped because ``alt_text``
    and frontmatter-sourced strings can contain characters like ``"`` or
    ``&`` that would otherwise break out of the attribute.
    """
    safe_href = html.escape(landing_url, quote=True)
    safe_cid = html.escape(thumbnail_cid, quote=True)
    safe_alt = html.escape(alt_text, quote=True)
    return (
        f'<a href="{safe_href}" style="display:inline-block;text-decoration:none;">'
        f'<img src="cid:{safe_cid}" alt="{safe_alt}" '
        f'style="max-width:100%;height:auto;display:block;border:0;border-radius:8px;" /></a>'
    )


def _replace_video_placeholder(
    rendered_html: str,
    landing_url: Optional[str],
    thumbnail_cid: Optional[str],
    alt_text: str,
) -> Tuple[str, bool]:
    """Replace the `<p>[video]</p>` block produced by markdown-it with the thumbnail anchor."""
    # After markdown-it rendering, `[video]` on its own line becomes `<p>[video]</p>`.
    pattern = re.compile(r"<p>\s*\[video\]\s*</p>")
    if not pattern.search(rendered_html):
        return rendered_html, False

    if not landing_url or not thumbnail_cid:
        logger.warning(
            "Body contains [video] but meta.yml is missing video_id/video_thumbnail — "
            "rendering a plain link to the newsletter landing page instead."
        )
        if landing_url:
            fallback = f'<p><a href="{html.escape(landing_url, quote=True)}">Watch the video</a></p>'
        else:
            fallback = "<p><em>[video placeholder — no landing URL configured]</em></p>"
        return pattern.sub(fallback, rendered_html, count=1), True

    replacement = f"<p>{_video_block_html(landing_url, thumbnail_cid, alt_text)}</p>"
    return pattern.sub(replacement, rendered_html, count=1), True


def render_issue(
    issue_dir: Path,
    lang: str,
    meta: IssueMeta,
    base_url: str,
) -> LocalizedIssue:
    """Render one language variant of a newsletter issue.

    The ``base_url`` is the deployed webapp origin (e.g. https://openmates.org
    in prod, http://localhost:5173 in dev) used to build the newsletter
    landing URL.
    """
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported language {lang!r}; expected one of {SUPPORTED_LANGS}")

    body_path = issue_dir / f"newsletter_{lang.upper()}.md"
    if not body_path.exists():
        raise FileNotFoundError(
            f"Newsletter body not found for language {lang!r}: {body_path}"
        )

    markdown_text = body_path.read_text(encoding="utf-8")
    if not markdown_text.strip():
        raise ValueError(f"Newsletter body is empty: {body_path}")

    frontmatter, body = _split_frontmatter(markdown_text)

    subject = frontmatter.get("subject") or frontmatter.get("title")
    if not subject:
        raise ValueError(
            f"{body_path.name} frontmatter must include a 'subject' (or 'title') field"
        )
    subtitle = frontmatter.get("subtitle")
    cta_text = frontmatter.get("cta_text")

    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
    html = md.render(body)

    landing_url = f"{base_url.rstrip('/')}/newsletter/{meta.slug}"
    thumbnail_cid = VIDEO_CID if meta.video_thumbnail_path else None
    alt_text = subtitle or subject
    html, has_video = _replace_video_placeholder(html, landing_url, thumbnail_cid, alt_text)

    if has_video and not meta.video_thumbnail_path:
        logger.warning(
            "Issue uses [video] marker but meta.yml has no video_thumbnail — "
            "recipients will see a plain text link, not a clickable image."
        )

    return LocalizedIssue(
        lang=lang,
        subject=subject.strip(),
        subtitle=subtitle.strip() if subtitle else None,
        cta_text=cta_text.strip() if cta_text else None,
        html_body=html,
        has_video=has_video,
    )


def build_video_thumbnail_attachment(meta: IssueMeta) -> Optional[Dict[str, Any]]:
    """Return an inline-attachment dict for the video thumbnail, or None.

    Uses the Brevo provider's attachment schema extended with a ``contentId``
    field for CID referencing. See BrevoProvider._process_attachments.
    """
    if not meta.video_thumbnail_path:
        return None

    content_b64 = base64.b64encode(meta.video_thumbnail_path.read_bytes()).decode("ascii")
    return {
        "filename": meta.video_thumbnail_path.name,
        "content": content_b64,
        "contentId": VIDEO_CID,
        "inline": True,
    }
