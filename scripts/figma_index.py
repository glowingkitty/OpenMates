#!/usr/bin/env python3
"""Build and search a private local index of OpenMates Figma surfaces.

The script fetches one complete Figma document, extracts root design surfaces
and short text-node beginnings, then writes an ignored local JSON index. It is
for design discovery only: Figma is a directional reference, not a web or Apple
parity contract. Credentials and generated design text are never committed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_PATH = REPO_ROOT / "scripts" / ".figma-index.json"
DEFAULT_FILE_KEY = "PzgE78TVxG0eWuEeO6o8ve"
DEFAULT_MAX_AGE_HOURS = 168.0
FIGMA_API_BASE_URL = "https://api.figma.com/v1"
FIGMA_DESIGN_BASE_URL = "https://www.figma.com/design"
TOKEN_ENV_NAME = "FIGMA_ACCESS_TOKEN"
TOKEN_FILES = (REPO_ROOT / ".env.figma.local", REPO_ROOT / ".env")
ARTBOARD_TYPES = frozenset({"FRAME", "COMPONENT", "COMPONENT_SET"})
INDEXED_TYPES = ARTBOARD_TYPES | {"SECTION"}
TEXT_SNIPPET_LENGTH = 160
REQUEST_TIMEOUT_SECONDS = 180
WORD_PATTERN = re.compile(r"[a-z0-9]+")
SEARCH_CONTEXT_WORDS = frozenset(
    {
        "artboard",
        "artboards",
        "check",
        "design",
        "figma",
        "frame",
        "frames",
        "in",
        "screen",
        "screens",
        "the",
        "ui",
        "ux",
    }
)


class FigmaIndexError(RuntimeError):
    """Raised for actionable, secret-safe Figma indexing failures."""


def normalize_text(value: str) -> str:
    """Normalize whitespace and Unicode for snippets and search comparisons."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _read_env_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        return value.strip().strip("'\"") or None
    return None


def load_access_token() -> str:
    """Load the Figma token without placing it in command output or the index."""
    token = os.environ.get(TOKEN_ENV_NAME)
    if token:
        return token
    for path in TOKEN_FILES:
        token = _read_env_value(path, TOKEN_ENV_NAME)
        if token:
            return token
    raise FigmaIndexError(
        f"Missing {TOKEN_ENV_NAME}. Add it to .env.figma.local or the process environment."
    )


def fetch_file(file_key: str, access_token: str) -> dict[str, Any]:
    """Fetch one complete Figma file while keeping authentication errors safe."""
    request = Request(
        f"{FIGMA_API_BASE_URL}/files/{file_key}",
        headers={"X-Figma-Token": access_token},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise FigmaIndexError(
            f"Figma API request failed with HTTP {exc.code} ({exc.reason})."
        ) from exc
    except URLError as exc:
        raise FigmaIndexError(f"Figma API request failed: {exc.reason}.") from exc
    except json.JSONDecodeError as exc:
        raise FigmaIndexError("Figma API returned invalid JSON.") from exc

    if not isinstance(payload, dict) or "document" not in payload:
        raise FigmaIndexError("Figma API response did not contain a document tree.")
    return payload


def _text_snippets(node: dict[str, Any]) -> list[str]:
    snippets: list[str] = []

    def visit(current: dict[str, Any]) -> None:
        if current.get("type") == "TEXT":
            value = current.get("characters") or current.get("name") or ""
            normalized = normalize_text(str(value))
            if normalized:
                snippets.append(normalized[:TEXT_SNIPPET_LENGTH])
        for child in current.get("children", []):
            if isinstance(child, dict):
                visit(child)

    visit(node)
    return snippets


def _surface_record(
    node: dict[str, Any],
    *,
    file_key: str,
    page_name: str,
    path: list[str],
) -> dict[str, Any]:
    bounding_box = node.get("absoluteBoundingBox") or {}
    node_id = str(node.get("id", ""))
    link_node_id = node_id.replace(":", "-")
    return {
        "id": node_id,
        "name": str(node.get("name", "Untitled")),
        "type": str(node.get("type", "UNKNOWN")),
        "page": page_name,
        "path": path,
        "visible": node.get("visible", True),
        "width": bounding_box.get("width"),
        "height": bounding_box.get("height"),
        "text_snippets": _text_snippets(node),
        "url": f"{FIGMA_DESIGN_BASE_URL}/{file_key}/OpenMates?node-id={link_node_id}",
    }


def build_index(payload: dict[str, Any], *, file_key: str) -> dict[str, Any]:
    """Extract sections and root artboards while retaining descendant text."""
    document = payload.get("document") or {}
    surfaces: list[dict[str, Any]] = []

    def visit(
        node: dict[str, Any],
        *,
        page_name: str,
        path: list[str],
        inside_artboard: bool,
    ) -> None:
        node_type = node.get("type")
        node_name = str(node.get("name", "Untitled"))
        current_path = [*path, node_name]

        is_section = node_type == "SECTION"
        is_root_artboard = node_type in ARTBOARD_TYPES and not inside_artboard
        if is_section or is_root_artboard:
            surfaces.append(
                _surface_record(
                    node,
                    file_key=file_key,
                    page_name=page_name,
                    path=current_path,
                )
            )

        child_inside_artboard = inside_artboard or is_root_artboard
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(
                    child,
                    page_name=page_name,
                    path=current_path,
                    inside_artboard=child_inside_artboard,
                )

    for page in document.get("children", []):
        if not isinstance(page, dict) or page.get("type") != "CANVAS":
            continue
        page_name = str(page.get("name", "Untitled page"))
        for child in page.get("children", []):
            if isinstance(child, dict):
                visit(
                    child,
                    page_name=page_name,
                    path=[page_name],
                    inside_artboard=False,
                )

    surfaces.sort(key=lambda item: (item["page"].casefold(), [part.casefold() for part in item["path"]]))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "file": {
            "key": file_key,
            "name": payload.get("name"),
            "last_modified": payload.get("lastModified"),
            "version": payload.get("version"),
        },
        "surface_count": len(surfaces),
        "surface_types": sorted(INDEXED_TYPES),
        "surfaces": surfaces,
    }


def write_index(index: dict[str, Any], path: Path) -> None:
    """Atomically write private design content with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def read_index(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FigmaIndexError(
            f"Figma index not found at {path}. Run `python3 scripts/figma_index.py refresh`."
        ) from exc
    except json.JSONDecodeError as exc:
        raise FigmaIndexError(f"Figma index at {path} contains invalid JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("surfaces"), list):
        raise FigmaIndexError(f"Figma index at {path} has an unsupported structure.")
    return payload


def is_index_fresh(
    index: dict[str, Any],
    *,
    max_age_hours: float,
    now: datetime | None = None,
) -> bool:
    generated_at = index.get("generated_at")
    if not isinstance(generated_at, str):
        return False
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return (current - generated).total_seconds() <= max_age_hours * 3600


def _words(value: str) -> set[str]:
    return set(WORD_PATTERN.findall(normalize_text(value).casefold()))


def _prefix_match(token: str, words: set[str]) -> bool:
    return any(word.startswith(token) or token.startswith(word) for word in words)


def _search_query(value: str) -> str:
    words = WORD_PATTERN.findall(normalize_text(value).casefold())
    meaningful_words = [word for word in words if word not in SEARCH_CONTEXT_WORDS]
    return " ".join(meaningful_words or words)


def _surface_score(surface: dict[str, Any], query: str) -> int:
    normalized_query = normalize_text(query).casefold()
    query_words = _words(normalized_query)
    name = normalize_text(str(surface.get("name", ""))).casefold()
    path = normalize_text(" ".join(surface.get("path", []))).casefold()
    text = normalize_text(" ".join(surface.get("text_snippets", []))).casefold()
    name_words = _words(name)
    path_words = _words(path)
    text_words = _words(text)
    score = 0

    if normalized_query == name:
        score += 300
    elif normalized_query in name:
        score += 180
    if normalized_query in path:
        score += 80
    if normalized_query in text:
        score += 30

    for token in query_words:
        if token in name_words:
            score += 45
        elif _prefix_match(token, name_words):
            score += 30
        if token in path_words:
            score += 15
        elif _prefix_match(token, path_words):
            score += 10
        if token in text_words:
            score += 3
        elif _prefix_match(token, text_words):
            score += 1

    score += {"FRAME": 12, "COMPONENT_SET": 8, "COMPONENT": 6, "SECTION": 4}.get(
        str(surface.get("type")), 0
    )
    return score if query_words and score > 12 else 0


def search_index(index: dict[str, Any], query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Rank surface names and paths ahead of incidental descendant copy."""
    effective_query = _search_query(query)
    results: list[dict[str, Any]] = []
    for surface in index.get("surfaces", []):
        if not isinstance(surface, dict):
            continue
        score = _surface_score(surface, effective_query)
        if score <= 0:
            continue
        results.append({**surface, "score": score})
    results.sort(
        key=lambda item: (
            -item["score"],
            item["name"].casefold(),
            item["id"],
        )
    )
    return results[:limit]


def refresh_index(file_key: str, index_path: Path) -> dict[str, Any]:
    payload = fetch_file(file_key, load_access_token())
    index = build_index(payload, file_key=file_key)
    write_index(index, index_path)
    return index


def _print_refresh_summary(index: dict[str, Any], path: Path) -> None:
    file_info = index["file"]
    print(
        f"Indexed {index['surface_count']} Figma surfaces from "
        f"{file_info.get('name') or file_info['key']} at {path}."
    )
    print(f"Figma version: {file_info.get('version') or 'unknown'}")


def _print_search_results(results: list[dict[str, Any]]) -> None:
    if not results:
        print("No matching Figma surfaces found.")
        return
    for position, result in enumerate(results, start=1):
        print(f"{position}. [{result['type']}] {' > '.join(result['path'])}")
        print(f"   Node: {result['id']} | Score: {result['score']}")
        snippets = result.get("text_snippets", [])[:3]
        if snippets:
            print(f"   Text: {' | '.join(snippets)}")
        print(f"   URL: {result['url']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help=f"Private local index path (default: {DEFAULT_INDEX_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="Fetch Figma and rebuild the local index")
    refresh.add_argument("--file-key", default=DEFAULT_FILE_KEY)

    ensure = subparsers.add_parser("ensure", help="Refresh only when the local index is stale")
    ensure.add_argument("--file-key", default=DEFAULT_FILE_KEY)
    ensure.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)

    search = subparsers.add_parser("search", help="Search the existing local index")
    search.add_argument("query", nargs="+", help="Design surface name or visible copy")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true", dest="json_output")

    subparsers.add_parser("status", help="Show local index freshness and file metadata")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index_path = args.index.resolve()
    try:
        if args.command == "refresh":
            index = refresh_index(args.file_key, index_path)
            _print_refresh_summary(index, index_path)
            return 0

        if args.command == "ensure":
            try:
                index = read_index(index_path)
            except FigmaIndexError:
                index = refresh_index(args.file_key, index_path)
                _print_refresh_summary(index, index_path)
                return 0
            if is_index_fresh(index, max_age_hours=args.max_age_hours):
                print(f"Figma index is fresh: {index_path}")
                return 0
            index = refresh_index(args.file_key, index_path)
            _print_refresh_summary(index, index_path)
            return 0

        index = read_index(index_path)
        if args.command == "search":
            results = search_index(index, " ".join(args.query), limit=max(args.limit, 1))
            if args.json_output:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                _print_search_results(results)
            return 0 if results else 1

        if args.command == "status":
            file_info = index["file"]
            print(f"Index: {index_path}")
            print(f"Generated: {index.get('generated_at') or 'unknown'}")
            print(f"File: {file_info.get('name') or file_info.get('key')}")
            print(f"Figma version: {file_info.get('version') or 'unknown'}")
            print(f"Surfaces: {index.get('surface_count', len(index['surfaces']))}")
            return 0
    except FigmaIndexError as exc:
        print(f"Figma index error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
