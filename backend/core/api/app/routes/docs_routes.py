# backend/core/api/app/routes/docs_routes.py
# Public documentation API — serves docs tree, individual docs, and search.
# Used by the CLI (`openmates docs`) and potentially third-party tools.
# Architecture: See docs/architecture/frontend/docs-web-app.md
# Tests: N/A — covered by CLI integration tests

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/docs",
    tags=["docs"],
)

# Resolve docs root relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parents[6]
_DOCS_ROOT = _PROJECT_ROOT / "docs"
_DOCSIGNORE = _DOCS_ROOT / ".docsignore"


def _load_ignore_patterns() -> list[str]:
    """Load .docsignore patterns."""
    if not _DOCSIGNORE.exists():
        return []
    patterns = []
    for line in _DOCSIGNORE.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def _should_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern."""
    normalized = rel_path.replace("\\", "/")
    for pattern in patterns:
        # Directory pattern (ends with /)
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            if normalized.startswith(dir_name + "/") or f"/{dir_name}/" in f"/{normalized}":
                return True
        # Glob pattern
        elif fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
            os.path.basename(normalized), pattern
        ):
            return True
    return False


def _build_tree(directory: Path, rel_prefix: str, ignore_patterns: list[str]) -> dict[str, Any]:
    """Recursively build a docs tree structure."""
    folders = []
    files = []

    if not directory.exists():
        return {"folders": folders, "files": files}

    for item in sorted(directory.iterdir()):
        rel_path = f"{rel_prefix}/{item.name}" if rel_prefix else item.name

        if _should_ignore(rel_path, ignore_patterns):
            continue

        if item.is_dir():
            subtree = _build_tree(item, rel_path, ignore_patterns)
            if subtree["folders"] or subtree["files"]:
                # Extract title from README.md if present
                readme = item / "README.md"
                title = item.name.replace("-", " ").title()
                if readme.exists():
                    first_line = readme.read_text(errors="replace").split("\n", 1)[0]
                    if first_line.startswith("# "):
                        title = first_line[2:].strip()
                folders.append({
                    "path": rel_path,
                    "title": title,
                    **subtree,
                })
        elif item.suffix == ".md":
            # Extract title from first heading
            content = item.read_text(errors="replace")
            first_line = content.split("\n", 1)[0]
            title = item.stem.replace("-", " ").title()
            if first_line.startswith("# "):
                title = first_line[2:].strip()

            slug = rel_path.replace(".md", "")
            word_count = len(content.split())
            files.append({
                "slug": slug,
                "title": title,
                "filename": item.name,
                "wordCount": word_count,
            })

    return {"folders": folders, "files": files}


@router.get("")
async def list_docs() -> dict[str, Any]:
    """Return the full documentation tree structure (titles, slugs, word counts)."""
    if not _DOCS_ROOT.exists():
        return {"folders": [], "files": []}
    ignore_patterns = _load_ignore_patterns()
    tree = _build_tree(_DOCS_ROOT, "", ignore_patterns)
    return tree


@router.get("/search")
async def search_docs(q: str = Query(..., min_length=1, max_length=200)) -> list[dict[str, Any]]:
    """Full-text search across all docs. Returns matching docs with title and snippet."""
    if not _DOCS_ROOT.exists():
        return []

    ignore_patterns = _load_ignore_patterns()
    query_lower = q.lower()
    results = []

    for md_file in sorted(_DOCS_ROOT.rglob("*.md")):
        rel_path = str(md_file.relative_to(_DOCS_ROOT)).replace("\\", "/")
        if _should_ignore(rel_path, ignore_patterns):
            continue

        content = md_file.read_text(errors="replace")
        content_lower = content.lower()

        if query_lower not in content_lower:
            continue

        # Extract title
        first_line = content.split("\n", 1)[0]
        title = md_file.stem.replace("-", " ").title()
        if first_line.startswith("# "):
            title = first_line[2:].strip()

        # Extract snippet around first match
        idx = content_lower.index(query_lower)
        start = max(0, idx - 80)
        end = min(len(content), idx + len(q) + 80)
        snippet = content[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        slug = rel_path.replace(".md", "")
        results.append({
            "slug": slug,
            "title": title,
            "snippet": snippet,
        })

        if len(results) >= 20:
            break

    return results


@router.get("/{slug:path}")
async def get_doc(slug: str) -> PlainTextResponse:
    """Return a single doc's raw markdown content by slug."""
    # Prevent path traversal
    if ".." in slug or slug.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid slug")

    ignore_patterns = _load_ignore_patterns()

    # Try exact path first
    doc_path = _DOCS_ROOT / f"{slug}.md"
    if not doc_path.exists():
        # Try as directory with README
        doc_path = _DOCS_ROOT / slug / "README.md"

    if not doc_path.exists() or not doc_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    rel_path = str(doc_path.relative_to(_DOCS_ROOT)).replace("\\", "/")
    if _should_ignore(rel_path, ignore_patterns):
        raise HTTPException(status_code=404, detail="Document not found")

    # Security: ensure resolved path is within docs root
    resolved = doc_path.resolve()
    if not str(resolved).startswith(str(_DOCS_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    content = doc_path.read_text(errors="replace")
    return PlainTextResponse(content, media_type="text/markdown")
