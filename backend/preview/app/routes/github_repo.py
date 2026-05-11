"""
GitHub Repository Metadata Endpoint

Fetches normalized public open-source repository metadata from GitHub.
Used for rich repo embeds when users paste GitHub repository URLs.

Endpoint: GET /api/v1/github-repo?url=...
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.shared.providers.github import build_github_repo_embed, parse_github_repo_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["github"])


@router.get("/github-repo")
async def get_github_repo(url: str) -> dict[str, Any]:
    """Return repo embed metadata for public licensed GitHub repositories."""
    if not parse_github_repo_url(url):
        raise HTTPException(status_code=400, detail="URL is not a GitHub repository root")

    try:
        metadata = await build_github_repo_embed(url)
    except Exception as exc:
        logger.warning("[GitHubRepo] Metadata fetch failed for %s: %s", url[:100], exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to fetch GitHub repository metadata") from exc

    if not metadata:
        raise HTTPException(status_code=404, detail="Repository is not public, licensed, or available")
    return metadata
