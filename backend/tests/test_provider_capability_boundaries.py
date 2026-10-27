"""Neutral unavailable capabilities and permitted-source routing contracts."""

# contract-test-file: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
from importlib import import_module
from pathlib import Path

import pytest
import yaml

from backend.apps.jobs.skills import search_skill as jobs
from backend.apps.social_media import collection, search_collection


@pytest.mark.parametrize(
    ("module", "class_name", "app", "skill"),
    [
        (
            "fitness.skills.search_locations",
            "SearchLocationsSkill",
            "fitness",
            "search_locations",
        ),
        (
            "fitness.skills.search_classes",
            "SearchClassesSkill",
            "fitness",
            "search_classes",
        ),
        (
            "electronics.skills.search_components",
            "SearchComponentsSkill",
            "electronics",
            "search_components",
        ),
        (
            "hosting.skills.search_domains",
            "SearchDomainsSkill",
            "hosting",
            "search_domains",
        ),
        (
            "business.skills.search_trademarks",
            "SearchTrademarksSkill",
            "business",
            "search_trademarks",
        ),
        ("models3d.skills.search_skill", "SearchSkill", "models3d", "search"),
    ],
)
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
async def test_empty_capability_metadata_and_execution_agree(
    module, class_name, app, skill
):
    cls = getattr(import_module(f"backend.apps.{module}"), class_name)
    instance = cls(
        app=None,
        app_id=app,
        skill_id=skill,
        skill_name="Search",
        skill_description="Search",
    )
    payload = await instance.execute(requests=[{"query": "sample"}])
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    assert payload["error"] == "No permitted provider is available for this capability."
    assert not payload.get("results", [])
    assert payload.get("success", False) is False
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "apps" / app / "app.yml").read_text()
    )
    metadata = next(item for item in config["skills"] if item["id"] == skill)
    assert metadata["provider_required"] is True
    assert metadata["providers"] == []


# contract-test: supporting surface=rest_api assertions=app-skills.providers.permitted-only
def test_jobs_allowlist_is_country_scoped_and_filters_fail_closed():
    assert set(jobs.PROVIDER_SEARCH) == {"jobtech"}
    assert jobs._provider_names(
        jobs.JobsSearchRequestItem(query="engineer"), ["SE"]
    ) == ["jobtech"]
    for request, countries in [
        ({"query": "engineer"}, ["DE"]),
        ({"query": "engineer", "radius_km": 10, "location": "Stockholm"}, ["SE"]),
        ({"query": "engineer", "employment_type": "internship"}, ["SE"]),
        ({"query": "engineer", "provider": "unsupported"}, ["SE"]),
    ]:
        with pytest.raises(ValueError):
            jobs._provider_names(jobs.JobsSearchRequestItem(**request), countries)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
async def test_jobs_uncovered_country_never_calls_remaining_source(monkeypatch):
    async def forbidden(**kwargs):
        pytest.fail("Unsupported country must not trigger a provider request")

    monkeypatch.setitem(jobs.PROVIDER_SEARCH, "jobtech", forbidden)
    skill = jobs.SearchSkill(
        app=None,
        app_id="jobs",
        skill_id="search",
        skill_name="Search",
        skill_description="Search",
    )
    response = await skill.execute(requests=[{"query": "engineer", "country": "DE"}])
    assert response.success is False
    assert response.results[0]["results"] == []
    assert "No requested jobs provider covers DE" in response.results[0]["error"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
async def test_social_unavailable_platform_has_no_fallback():
    posts = await collection.collect_posts(
        [{"platform": "unsupported", "page": "sample"}]
    )
    searches = await search_collection.collect_search_results(
        [{"platform": "unsupported", "query": "sample"}]
    )
    for item in [*posts, *searches]:
        assert item.errors
        assert item.posts == []
        assert item.request_count == 0
    assert collection.SUPPORTED_PLATFORMS == {"bluesky", "mastodon"}
    assert search_collection.DEFAULT_SEARCH_PLATFORMS == ("bluesky", "mastodon")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.providers.permitted-only
async def test_jobs_retained_source_preserves_strict_filters(monkeypatch):
    seen = []

    async def source(**kwargs):
        seen.append(kwargs)
        return [
            {
                "id": "remote",
                "title": "Engineer",
                "url": "https://example.org/remote",
                "country": "SE",
                "remote": True,
                "employment_type": "full_time",
            },
            {
                "id": "unknown",
                "title": "Engineer",
                "url": "https://example.org/unknown",
                "country": "SE",
                "remote": None,
                "employment_type": "full_time",
            },
            {
                "id": "wrong-country",
                "title": "Engineer",
                "url": "https://example.org/elsewhere",
                "country": "DE",
                "remote": True,
                "employment_type": "full_time",
            },
        ]

    monkeypatch.setitem(jobs.PROVIDER_SEARCH, "jobtech", source)
    skill = jobs.SearchSkill(
        app=None,
        app_id="jobs",
        skill_id="search",
        skill_name="Search",
        skill_description="Search",
    )
    response = await skill.execute(
        countries=["SE"],
        requests=[
            {
                "query": "engineer",
                "remote": True,
                "employment_type": "full_time",
            }
        ],
    )
    assert response.success
    assert seen[0]["remote"] is True
    assert seen[0]["country"] == "SE"
    assert [item["id"] for item in response.results[0]["results"]] == ["remote"]
    assert response.providers == ["jobtech"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.providers.permitted-only
async def test_social_default_search_calls_only_remaining_sources(monkeypatch):
    calls = []

    async def collect(request_id, item, *args, **kwargs):
        calls.append("bluesky")
        return search_collection.SearchResponseItem(
            id=request_id, platform="bluesky", query=item.query, sort="latest"
        )

    async def search(request_id, item):
        calls.append("mastodon")
        return search_collection.SearchResponseItem(
            id=request_id, platform="mastodon", query=item.query, sort="latest"
        )

    monkeypatch.setattr(search_collection, "_search_bluesky", collect)
    monkeypatch.setattr(search_collection, "_search_mastodon", search)
    results = await search_collection.collect_search_results([{"query": "sample"}])
    assert calls == ["bluesky", "mastodon"]
    assert [item.platform for item in results] == calls
