# backend/shared/providers/github/repo_metadata.py
#
# GitHub repository metadata provider used by repo embeds.
# Keeps GitHub API access server-side so clients do not directly contact GitHub
# for pasted repo URLs, and so web-search results can be enriched consistently.
#
# The provider only returns public, open-source-ish repositories. Private,
# disabled, missing, or unlicensed repositories return None so callers can fall
# back to the normal website embed path.

from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TIMEOUT_SECONDS = 12
GITHUB_REPO_PATH_RE = re.compile(r"^/([^/]+)/([^/]+?)(?:\.git)?/?$")
MIT_LICENSE_MARKER = "MIT License"


def parse_github_repo_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) for canonical GitHub repository URLs only."""
    if not url or not isinstance(url, str):
        return None

    candidate = url.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None

    match = GITHUB_REPO_PATH_RE.match(parsed.path)
    if not match:
        return None

    owner, repo = match.group(1), match.group(2)
    if owner in {"features", "topics", "collections", "marketplace", "explore", "login", "orgs"}:
        return None
    if not owner or not repo or repo in {"issues", "pulls", "pull", "tree", "blob", "commit", "releases"}:
        return None
    return owner, repo.removesuffix(".git")


def is_github_repo_url(url: str) -> bool:
    """Return true when the URL points to a GitHub repo root."""
    return parse_github_repo_url(url) is not None


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpenMates-Repo-Embed",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("SECRET__GITHUB__TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


async def _get_json(client: httpx.AsyncClient, path: str) -> Any | None:
    response = await client.get(f"{GITHUB_API_BASE}{path}")
    if response.status_code == 404:
        return None
    if response.status_code == 403:
        logger.warning("GitHub API rate limited or forbidden for path %s", path)
        return None
    response.raise_for_status()
    return response.json()


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return value


def _clean_text(value: Any, max_length: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:max_length] if cleaned else None


def _canonical_url(owner: str, repo: str) -> str:
    return urlunparse(("https", "github.com", f"/{owner}/{repo}", "", "", ""))


def _decode_license_text(license_payload: Any) -> str:
    if not isinstance(license_payload, dict):
        return ""
    content = license_payload.get("content")
    if not isinstance(content, str):
        return ""
    try:
        return base64.b64decode(content, validate=False).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _normalise_license(repo_payload: dict[str, Any], license_payload: Any) -> tuple[str | None, str | None]:
    repo_license = repo_payload.get("license") if isinstance(repo_payload.get("license"), dict) else {}
    name = _clean_text(repo_license.get("name"), 120)
    spdx = _clean_text(repo_license.get("spdx_id"), 40)

    license_obj = license_payload.get("license") if isinstance(license_payload, dict) else None
    if isinstance(license_obj, dict):
        name = _clean_text(license_obj.get("name"), 120) or name
        spdx = _clean_text(license_obj.get("spdx_id"), 40) or spdx

    text = _decode_license_text(license_payload)
    if (not spdx or spdx == "NOASSERTION") and MIT_LICENSE_MARKER.lower() in text.lower():
        return "MIT License", "MIT"
    if spdx == "NOASSERTION" and name == "Other" and not text.strip():
        return None, None
    return name, spdx


def _language_percentages(languages: Any) -> list[dict[str, Any]]:
    if not isinstance(languages, dict):
        return []
    total = sum(v for v in languages.values() if isinstance(v, int) and v > 0)
    if total <= 0:
        return []
    rows = []
    for language, bytes_count in sorted(languages.items(), key=lambda item: item[1], reverse=True):
        if not isinstance(bytes_count, int) or bytes_count <= 0:
            continue
        rows.append({
            "language": language,
            "bytes": bytes_count,
            "percent": round((bytes_count / total) * 100, 1),
        })
    return rows[:8]


async def build_github_repo_embed(url: str) -> dict[str, Any] | None:
    """Fetch and normalize metadata for a public licensed GitHub repository."""
    parsed = parse_github_repo_url(url)
    if not parsed:
        return None
    owner, repo = parsed

    async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS, headers=_github_headers()) as client:
        repo_payload = await _get_json(client, f"/repos/{owner}/{repo}")
        if not isinstance(repo_payload, dict):
            return None

        if repo_payload.get("private") is not False or repo_payload.get("visibility") != "public":
            return None
        if repo_payload.get("disabled") is True:
            return None

        languages_payload = await _get_json(client, f"/repos/{owner}/{repo}/languages") or {}
        license_payload = await _get_json(client, f"/repos/{owner}/{repo}/license") or {}
        release_payload = await _get_json(client, f"/repos/{owner}/{repo}/releases/latest") or {}
        commits_payload = await _get_json(client, f"/repos/{owner}/{repo}/commits?per_page=1") or []
        contributors_payload = await _get_json(client, f"/repos/{owner}/{repo}/contributors?per_page=5") or []

    license_name, license_spdx = _normalise_license(repo_payload, license_payload)
    if not license_name and not license_spdx:
        logger.info("Skipping GitHub repo embed without detectable license: %s/%s", owner, repo)
        return None

    owner_payload = repo_payload.get("owner") if isinstance(repo_payload.get("owner"), dict) else {}
    latest_commit = commits_payload[0] if isinstance(commits_payload, list) and commits_payload else {}
    latest_commit_data = latest_commit.get("commit") if isinstance(latest_commit, dict) else {}
    latest_commit_author = latest_commit_data.get("author") if isinstance(latest_commit_data, dict) else {}

    contributors: list[dict[str, Any]] = []
    if isinstance(contributors_payload, list):
        for contributor in contributors_payload[:5]:
            if not isinstance(contributor, dict):
                continue
            login = _clean_text(contributor.get("login"), 80)
            if not login:
                continue
            contributors.append({
                "login": login,
                "avatar_url": _clean_text(contributor.get("avatar_url"), 300),
                "html_url": _clean_text(contributor.get("html_url"), 300),
                "contributions": contributor.get("contributions") if isinstance(contributor.get("contributions"), int) else None,
            })

    languages = _language_percentages(languages_payload)
    canonical_url = _canonical_url(owner, repo)
    return {
        "url": canonical_url,
        "html_url": repo_payload.get("html_url") or canonical_url,
        "full_name": repo_payload.get("full_name") or f"{owner}/{repo}",
        "owner_login": owner_payload.get("login") or owner,
        "owner_avatar_url": owner_payload.get("avatar_url"),
        "name": repo_payload.get("name") or repo,
        "description": _clean_text(repo_payload.get("description"), 500),
        "visibility": "public",
        "private": False,
        "fork": bool(repo_payload.get("fork")),
        "archived": bool(repo_payload.get("archived")),
        "disabled": bool(repo_payload.get("disabled")),
        "is_template": bool(repo_payload.get("is_template")),
        "default_branch": repo_payload.get("default_branch") or "main",
        "primary_language": repo_payload.get("language"),
        "languages": languages,
        "topics": repo_payload.get("topics") if isinstance(repo_payload.get("topics"), list) else [],
        "license_name": license_name,
        "license_spdx_id": license_spdx,
        "stars": repo_payload.get("stargazers_count") or 0,
        "forks": repo_payload.get("forks_count") or 0,
        "watchers": repo_payload.get("watchers_count") or 0,
        "subscribers": repo_payload.get("subscribers_count"),
        "open_issues": repo_payload.get("open_issues_count") or 0,
        "created_at": _iso_date(repo_payload.get("created_at")),
        "updated_at": _iso_date(repo_payload.get("updated_at")),
        "pushed_at": _iso_date(repo_payload.get("pushed_at")),
        "latest_release_tag": release_payload.get("tag_name") if isinstance(release_payload, dict) else None,
        "latest_release_name": release_payload.get("name") if isinstance(release_payload, dict) else None,
        "latest_release_published_at": _iso_date(release_payload.get("published_at")) if isinstance(release_payload, dict) else None,
        "latest_commit_sha": latest_commit.get("sha") if isinstance(latest_commit, dict) else None,
        "latest_commit_message": _clean_text(latest_commit_data.get("message"), 300) if isinstance(latest_commit_data, dict) else None,
        "latest_commit_date": _iso_date(latest_commit_author.get("date")) if isinstance(latest_commit_author, dict) else None,
        "contributors": contributors,
        "site_name": "GitHub",
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
