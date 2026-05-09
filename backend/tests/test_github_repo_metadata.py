# backend/tests/test_github_repo_metadata.py
#
# Unit coverage for the GitHub repository metadata provider used by repo embeds.
# These tests mock GitHub API calls so the open-source gate and normalized embed
# payload stay deterministic without relying on network access or live repos.
#
# The provider must only return public, licensed repositories. Non-repo URLs,
# private/disabled repos, and repos without a detectable license should fall back
# to the normal website embed path.

from __future__ import annotations

import base64

import pytest

from backend.shared.providers.github import repo_metadata


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status_code}")

    def json(self):
        return self._payload


class _FakeAsyncClient:
    responses: dict[str, _FakeResponse] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        path = url.removeprefix(repo_metadata.GITHUB_API_BASE)
        return self.responses.get(path, _FakeResponse({}, 404))


def _repo_payload(**overrides):
    payload = {
        "html_url": "https://github.com/openmates/example",
        "full_name": "openmates/example",
        "name": "example",
        "description": "Example repo\nwith whitespace",
        "private": False,
        "visibility": "public",
        "disabled": False,
        "fork": False,
        "archived": False,
        "is_template": False,
        "default_branch": "main",
        "language": "TypeScript",
        "topics": ["embeds", "github"],
        "license": {"name": "MIT License", "spdx_id": "MIT"},
        "stargazers_count": 42,
        "forks_count": 7,
        "watchers_count": 42,
        "subscribers_count": 5,
        "open_issues_count": 3,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-02-01T00:00:00Z",
        "pushed_at": "2024-03-01T00:00:00Z",
        "owner": {
            "login": "openmates",
            "avatar_url": "https://avatars.githubusercontent.com/u/123",
        },
    }
    payload.update(overrides)
    return payload


def _license_payload(spdx_id: str = "MIT", name: str = "MIT License", text: str = "MIT License\nPermission is hereby granted"):
    return {
        "license": {"name": name, "spdx_id": spdx_id},
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    }


def test_parse_github_repo_url_accepts_canonical_repo_urls():
    assert repo_metadata.parse_github_repo_url("https://github.com/openmates/example") == ("openmates", "example")
    assert repo_metadata.parse_github_repo_url("github.com/openmates/example.git") == ("openmates", "example")
    assert repo_metadata.is_github_repo_url("https://www.github.com/openmates/example") is True


def test_parse_github_repo_url_rejects_non_repo_paths():
    assert repo_metadata.parse_github_repo_url("https://github.com/openmates/example/issues") is None
    assert repo_metadata.parse_github_repo_url("https://github.com/features") is None
    assert repo_metadata.parse_github_repo_url("https://gitlab.com/openmates/example") is None


@pytest.mark.asyncio
async def test_build_github_repo_embed_returns_normalized_public_licensed_repo(monkeypatch):
    _FakeAsyncClient.responses = {
        "/repos/openmates/example": _FakeResponse(_repo_payload()),
        "/repos/openmates/example/languages": _FakeResponse({"TypeScript": 900, "Python": 100}),
        "/repos/openmates/example/license": _FakeResponse(_license_payload()),
        "/repos/openmates/example/releases/latest": _FakeResponse({"tag_name": "v1.2.3", "name": "Release 1.2.3", "published_at": "2024-04-01T00:00:00Z"}),
        "/repos/openmates/example/commits?per_page=1": _FakeResponse([{"sha": "abc123", "commit": {"message": "Ship repo embeds", "author": {"date": "2024-05-01T00:00:00Z"}}}]),
        "/repos/openmates/example/contributors?per_page=5": _FakeResponse([{"login": "mate", "avatar_url": "https://avatars.githubusercontent.com/u/456", "html_url": "https://github.com/mate", "contributions": 12}]),
    }
    monkeypatch.setattr(repo_metadata.httpx, "AsyncClient", _FakeAsyncClient)

    embed = await repo_metadata.build_github_repo_embed("https://github.com/openmates/example")

    assert embed is not None
    assert embed["url"] == "https://github.com/openmates/example"
    assert embed["full_name"] == "openmates/example"
    assert embed["description"] == "Example repo with whitespace"
    assert embed["visibility"] == "public"
    assert embed["license_spdx_id"] == "MIT"
    assert embed["stars"] == 42
    assert embed["languages"][0] == {"language": "TypeScript", "bytes": 900, "percent": 90.0}
    assert embed["latest_release_tag"] == "v1.2.3"
    assert embed["latest_commit_message"] == "Ship repo embeds"
    assert embed["contributors"][0]["login"] == "mate"


@pytest.mark.asyncio
async def test_build_github_repo_embed_skips_private_repos(monkeypatch):
    _FakeAsyncClient.responses = {
        "/repos/openmates/private": _FakeResponse(_repo_payload(full_name="openmates/private", name="private", private=True, visibility="private")),
    }
    monkeypatch.setattr(repo_metadata.httpx, "AsyncClient", _FakeAsyncClient)

    assert await repo_metadata.build_github_repo_embed("https://github.com/openmates/private") is None


@pytest.mark.asyncio
async def test_build_github_repo_embed_skips_repos_without_detectable_license(monkeypatch):
    _FakeAsyncClient.responses = {
        "/repos/openmates/unlicensed": _FakeResponse(_repo_payload(full_name="openmates/unlicensed", name="unlicensed", license={"name": "Other", "spdx_id": "NOASSERTION"})),
        "/repos/openmates/unlicensed/languages": _FakeResponse({}),
        "/repos/openmates/unlicensed/license": _FakeResponse(_license_payload(spdx_id="NOASSERTION", name="Other", text="")),
        "/repos/openmates/unlicensed/releases/latest": _FakeResponse({}, 404),
        "/repos/openmates/unlicensed/commits?per_page=1": _FakeResponse([]),
        "/repos/openmates/unlicensed/contributors?per_page=5": _FakeResponse([]),
    }
    monkeypatch.setattr(repo_metadata.httpx, "AsyncClient", _FakeAsyncClient)

    assert await repo_metadata.build_github_repo_embed("https://github.com/openmates/unlicensed") is None
