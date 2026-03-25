#!/usr/bin/env python3
"""
Fix relative markdown links in docs/ after major restructuring.

Two-pass approach:
1. For links that resolve to a known old path on disk -> rewrite to new path
2. For files that were themselves moved, resolve links from the OLD location
   to find what old path was intended, then rewrite to the new target

Handles anchor fragments (e.g., message-processing.md#tool-preselection).
"""

import os
import re
from pathlib import Path

DOCS_ROOT = Path(__file__).parent.parent / "docs"

# Old path (relative to repo root) -> New path (relative to repo root)
PATH_MAPPING = {
    # Architecture -> core/
    "docs/architecture/servers.md": "docs/architecture/core/servers.md",
    "docs/architecture/security.md": "docs/architecture/core/security.md",
    "docs/architecture/zero-knowledge-storage.md": "docs/architecture/core/zero-knowledge-storage.md",
    "docs/architecture/signup-and-auth.md": "docs/architecture/core/signup-and-auth.md",
    "docs/architecture/passkeys.md": "docs/architecture/core/passkeys.md",
    "docs/architecture/account-recovery.md": "docs/architecture/core/account-recovery.md",
    "docs/architecture/account-backup.md": "docs/architecture/core/account-backup.md",
    # Architecture -> messaging/
    "docs/architecture/message-processing.md": "docs/architecture/messaging/message-processing.md",
    "docs/architecture/message-parsing.md": "docs/architecture/messaging/message-parsing.md",
    "docs/architecture/message-input-field.md": "docs/architecture/messaging/message-input-field.md",
    "docs/architecture/message-previews-grouping.md": "docs/architecture/messaging/message-previews-grouping.md",
    "docs/architecture/embeds.md": "docs/architecture/messaging/embeds.md",
    # Architecture -> ai/
    "docs/architecture/ai-model-selection.md": "docs/architecture/ai/ai-model-selection.md",
    "docs/architecture/thinking-models.md": "docs/architecture/ai/thinking-models.md",
    "docs/architecture/hallucination-mitigation.md": "docs/architecture/ai/hallucination-mitigation.md",
    "docs/architecture/preprocessing-model-comparison.md": "docs/architecture/ai/preprocessing-model-comparison.md",
    "docs/architecture/mates.md": "docs/architecture/ai/mates.md",
    "docs/architecture/followup-suggestions.md": "docs/architecture/ai/followup-suggestions.md",
    # Architecture -> privacy/
    "docs/architecture/pii-protection.md": "docs/architecture/privacy/pii-protection.md",
    "docs/architecture/prompt-injection.md": "docs/architecture/privacy/prompt-injection.md",
    "docs/architecture/sensitive-data-redaction.md": "docs/architecture/privacy/sensitive-data-redaction.md",
    "docs/architecture/email-privacy.md": "docs/architecture/privacy/email-privacy.md",
    # Architecture -> data/
    "docs/architecture/sync.md": "docs/architecture/data/sync.md",
    "docs/architecture/device-sessions.md": "docs/architecture/data/device-sessions.md",
    "docs/architecture/translations.md": "docs/architecture/data/translations.md",
    # Architecture -> payments/
    "docs/architecture/payment-processing.md": "docs/architecture/payments/payment-processing.md",
    # Architecture -> frontend/
    "docs/architecture/web-app.md": "docs/architecture/frontend/web-app.md",
    "docs/architecture/docs-web-app.md": "docs/architecture/frontend/docs-web-app.md",
    "docs/architecture/daily-inspiration.md": "docs/architecture/frontend/daily-inspiration.md",
    "docs/architecture/accessibility.md": "docs/architecture/frontend/accessibility.md",
    # Architecture -> infrastructure/
    "docs/architecture/health-checks.md": "docs/architecture/infrastructure/health-checks.md",
    "docs/architecture/logging.md": "docs/architecture/infrastructure/logging.md",
    "docs/architecture/admin-console-log-forwarding.md": "docs/architecture/infrastructure/admin-console-log-forwarding.md",
    "docs/architecture/cronjobs.md": "docs/architecture/infrastructure/cronjobs.md",
    "docs/architecture/developer-settings.md": "docs/architecture/infrastructure/developer-settings.md",
    "docs/architecture/file-upload-pipeline.md": "docs/architecture/infrastructure/file-upload-pipeline.md",
    "docs/architecture/status-page.md": "docs/architecture/infrastructure/status-page.md",
    "docs/architecture/vector-personalization.md": "docs/architecture/infrastructure/vector-personalization.md",
    # Architecture -> storage/
    "docs/architecture/embed-cold-storage.md": "docs/architecture/storage/embed-cold-storage.md",
    # Architecture -> apps/
    "docs/architecture/app-skills.md": "docs/architecture/apps/app-skills.md",
    "docs/architecture/rest-api.md": "docs/architecture/apps/rest-api.md",
    # Architecture -> special moves
    "docs/architecture/settings-ui.md": "docs/design-guide/settings-ui.md",
    "docs/architecture/openmates-cli.md": "docs/cli/openmates-cli-old.md",
    # Top-level docs moved
    "docs/analytics.md": "docs/architecture/infrastructure/analytics.md",
    "docs/media-generation.md": "docs/architecture/integrations/media-generation.md",
    # docs/apis/ -> architecture/integrations/
    "docs/apis/luma.md": "docs/architecture/integrations/luma.md",
    # docs/apps/ -> split between architecture/apps/ and user-guide/apps/
    "docs/apps/function-calling.md": "docs/architecture/apps/function-calling.md",
    "docs/apps/focus-modes-implementation.md": "docs/architecture/apps/focus-modes-implementation.md",
    "docs/apps/action-confirmation.md": "docs/architecture/apps/action-confirmation.md",
    "docs/apps/README.md": "docs/user-guide/apps/README.md",
    "docs/apps/app-store.md": "docs/user-guide/apps/app-store.md",
    "docs/apps/books.md": "docs/user-guide/apps/books.md",
    "docs/apps/business.md": "docs/user-guide/apps/business.md",
    "docs/apps/coaching.md": "docs/user-guide/apps/coaching.md",
    "docs/apps/code.md": "docs/user-guide/apps/code.md",
    "docs/apps/contacts.md": "docs/user-guide/apps/contacts.md",
    "docs/apps/design.md": "docs/user-guide/apps/design.md",
    "docs/apps/docs.md": "docs/user-guide/apps/docs.md",
    "docs/apps/drawing.md": "docs/user-guide/apps/drawing.md",
    "docs/apps/events.md": "docs/user-guide/apps/events.md",
    "docs/apps/files.md": "docs/user-guide/apps/files.md",
    "docs/apps/fitness.md": "docs/user-guide/apps/fitness.md",
    "docs/apps/focus-modes.md": "docs/user-guide/apps/focus-modes.md",
    "docs/apps/health.md": "docs/user-guide/apps/health.md",
    "docs/apps/home.md": "docs/user-guide/apps/home.md",
    "docs/apps/images.md": "docs/user-guide/apps/images.md",
    "docs/apps/jobs.md": "docs/user-guide/apps/jobs.md",
    "docs/apps/mail.md": "docs/user-guide/apps/mail.md",
    "docs/apps/maps.md": "docs/user-guide/apps/maps.md",
    "docs/apps/math.md": "docs/user-guide/apps/math.md",
    "docs/apps/music.md": "docs/user-guide/apps/music.md",
    "docs/apps/news.md": "docs/user-guide/apps/news.md",
    "docs/apps/pdf.md": "docs/user-guide/apps/pdf.md",
    "docs/apps/plants.md": "docs/user-guide/apps/plants.md",
    "docs/apps/reminder.md": "docs/user-guide/apps/reminder.md",
    "docs/apps/settings-and-memories.md": "docs/user-guide/apps/settings-and-memories.md",
    "docs/apps/sheets.md": "docs/user-guide/apps/sheets.md",
    "docs/apps/shopping.md": "docs/user-guide/apps/shopping.md",
    "docs/apps/skills.md": "docs/user-guide/apps/skills.md",
    "docs/apps/slides.md": "docs/user-guide/apps/slides.md",
    "docs/apps/study.md": "docs/user-guide/apps/study.md",
    "docs/apps/travel.md": "docs/user-guide/apps/travel.md",
    "docs/apps/videos.md": "docs/user-guide/apps/videos.md",
    "docs/apps/web.md": "docs/user-guide/apps/web.md",
    # docs/contributing/ -> architecture/contributing/
    "docs/contributing/README.md": "docs/architecture/contributing/README.md",
    "docs/contributing/contributing.md": "docs/architecture/contributing/contributing.md",
    # docs/getting-started/
    "docs/getting-started/README.md": "docs/user-guide/getting-started.md",
}

# Regex to match markdown links: [text](path) but not images ![text](path)
LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]*)\]\(([^)]+)\)')

REPO_ROOT = DOCS_ROOT.parent
EXCLUDE_DIRS = {"claude", "internal", "images", "planned"}

# Build reverse mapping: new path -> old path
REVERSE_MAPPING = {v: k for k, v in PATH_MAPPING.items()}


def get_old_location(filepath: Path) -> Path | None:
    """If this file was moved, return its old absolute path."""
    try:
        repo_rel = str(filepath.relative_to(REPO_ROOT))
    except ValueError:
        return None
    if repo_rel in REVERSE_MAPPING:
        return REPO_ROOT / REVERSE_MAPPING[repo_rel]
    return None


def normalize_path(path_str: str) -> str:
    """Normalize a repo-relative path string (collapse .., remove .)."""
    return str(Path(path_str))


def try_resolve_link(link_path: str, from_dir: Path) -> str | None:
    """
    Try to resolve a relative link from a directory.
    Returns the repo-relative path string if it matches a known old path, else None.
    Uses pure path manipulation (no filesystem resolve) to handle non-existent paths.
    """
    # Use posixpath-style joining
    combined = os.path.normpath(os.path.join(str(from_dir), link_path))
    try:
        repo_rel = os.path.relpath(combined, str(REPO_ROOT))
    except ValueError:
        return None
    # Normalize
    repo_rel = repo_rel.replace("\\", "/")
    if repo_rel in PATH_MAPPING:
        return repo_rel
    return None


def compute_new_relative(target_repo_path: str, from_dir: Path) -> str:
    """Compute a relative path from from_dir to the target (repo-relative path)."""
    target_abs = REPO_ROOT / target_repo_path
    rel = os.path.relpath(str(target_abs), str(from_dir))
    rel = rel.replace("\\", "/")
    # Add ./ prefix for same-directory references
    if "/" not in rel:
        rel = "./" + rel
    return rel


def collect_md_files():
    """Collect all .md files in docs/ excluding certain directories."""
    md_files = []
    for root, dirs, files in os.walk(DOCS_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".md"):
                md_files.append(Path(root) / f)
    return sorted(md_files)


def fix_links_in_file(filepath: Path) -> list[tuple[str, str]]:
    """Fix broken links in a single file. Returns list of (old_link, new_link) changes."""
    content = filepath.read_text()
    file_dir = filepath.parent
    old_location = get_old_location(filepath)
    old_dir = old_location.parent if old_location else None
    changes = []

    def replace_link(match):
        full_match = match.group(0)
        link_text = match.group(1)
        link_target = match.group(2)

        # Skip external links, anchors-only, and non-relative paths
        if link_target.startswith(("http://", "https://", "mailto:", "#", "/")):
            return full_match

        # Split off anchor fragment
        if "#" in link_target:
            path_part, anchor = link_target.split("#", 1)
            anchor = "#" + anchor
        else:
            path_part = link_target
            anchor = ""

        if not path_part:
            return full_match

        # Strategy 1: Resolve from current location
        old_repo_path = try_resolve_link(path_part, file_dir)

        # Strategy 2: If file was moved, resolve from OLD location
        if old_repo_path is None and old_dir is not None:
            old_repo_path = try_resolve_link(path_part, old_dir)

        if old_repo_path is None:
            return full_match

        # Get the new target path
        new_target = PATH_MAPPING[old_repo_path]

        # Compute new relative path from current file's directory
        new_rel = compute_new_relative(new_target, file_dir)

        new_link = f"[{link_text}]({new_rel}{anchor})"

        if new_link != full_match:
            changes.append((link_target, f"{new_rel}{anchor}"))
            return new_link

        return full_match

    new_content = LINK_PATTERN.sub(replace_link, content)

    if new_content != content:
        filepath.write_text(new_content)

    return changes


def main():
    md_files = collect_md_files()
    print(f"Scanning {len(md_files)} markdown files...\n")

    total_changes = 0
    files_changed = 0

    for filepath in md_files:
        changes = fix_links_in_file(filepath)
        if changes:
            files_changed += 1
            rel_path = filepath.relative_to(REPO_ROOT)
            print(f"  {rel_path}:")
            for old_link, new_link in changes:
                print(f"    {old_link}")
                print(f"      -> {new_link}")
            total_changes += len(changes)

    print(f"\n{'='*60}")
    print(f"Summary: Fixed {total_changes} links across {files_changed} files")
    print(f"Total files scanned: {len(md_files)}")


if __name__ == "__main__":
    main()
