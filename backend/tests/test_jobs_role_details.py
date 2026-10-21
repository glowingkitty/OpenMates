"""Hard Problems detail fidelity, outbound request bounds and graceful failures."""

import asyncio
import json

import httpx
import pytest

from backend.shared.providers.jobs import hard_problems
from backend.shared.providers.jobs.common import ProviderError
from backend.shared.providers.jobs.hard_problems_details import MAX_DETAIL_BYTES, fetch_role_details, parse_role_details

pytestmark = pytest.mark.anyio
URL = "https://www.hardproblems.com/jobs/role/test-designer"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def page(url=URL):
    posting = {"@type": "JobPosting", "url": url, "employmentType": "FULL_TIME",
               "description": "Build useful tools.\n## Requirements\nExperience designing accessible products.\n## Benefits\n30 days of annual leave. <script>unsafe()</script>",
               "validThrough": "2026-11-14T00:00:00Z"}
    encoded = json.dumps(posting).replace("<", r"\u003c")
    return f'<script type="application/ld+json">{encoded}</script><main><dl>' + (
        '<dt>Sector</dt><dd><span>Healthcare</span></dd><dt>Role</dt><dd>Product design</dd>'
        '<dt>Seniority</dt><dd>Senior</dd><dt>Organisation</dt><dd>For-profit</dd>'
        '<dt>On-site or remote</dt><dd>Remote</dd><dt>Salary</dt><dd>n/a</dd></dl></main>')


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_role_details_preserve_description_facts_and_unknown_pay():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=page())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await fetch_role_details(client, URL)
    assert len(requests) == 1 and str(requests[0].url) == URL
    assert result["sector"] == "Healthcare"
    assert result["role"] == "Product design"
    assert result["seniority"] == "Senior"
    assert result["organization_type"] == "For-profit"
    assert result["work_arrangement"] == "Remote"
    assert result["employment_type"] == "full_time"
    assert result["valid_through"] == "2026-11-14T00:00:00Z"
    assert "accessible products" in result["description"]
    assert "30 days of annual leave" in result["description"]
    assert "unsafe" not in result["description"] and "<script>" not in result["description"]
    assert "##" not in result["description"]
    assert "salary_text" not in result
    assert result["detail_status"] == "complete"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_detail_http_rejects_untrusted_urls_redirects_and_oversized_pages():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for url in ["https://127.0.0.1/jobs/role/test", "https://employer.example/jobs/role/test", "https://www.hardproblems.com/private"]:
            with pytest.raises(ProviderError):
                await fetch_role_details(client, url)
        assert seen == []
        with pytest.raises(ProviderError):
            await fetch_role_details(client, URL)
        assert len(seen) == 1  # redirect target was never requested
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (MAX_DETAIL_BYTES + 1)))) as client:
        with pytest.raises(ProviderError, match="bounded size"):
            await fetch_role_details(client, URL)
    with pytest.raises(ProviderError):
        parse_role_details(page("https://www.hardproblems.com/jobs/role/a-different-job"), URL)
    with pytest.raises(ProviderError):
        parse_role_details('<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "url": URL, "description": ""
        }) + '</script>', URL)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_detail_failure_preserves_summary_and_exposes_incomplete_state(monkeypatch):
    async def unavailable(*args):
        raise ProviderError("unavailable", "Safe failure")
    monkeypatch.setattr(hard_problems, "fetch_role_details", unavailable)
    listing = {"id": "hard_problems:test", "url": URL, "description": "Feed summary.", "detail_status": "summary"}
    result = await hard_problems._enrich_listing(None, asyncio.Semaphore(3), listing)
    assert result == listing and result["detail_status"] == "summary"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
async def test_detail_enrichment_is_bounded_and_keeps_source_identity(monkeypatch):
    active = peak = 0
    async def details(client, url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return {"sector": "Healthcare", "description": "Full role details.", "detail_status": "complete"}
    monkeypatch.setattr(hard_problems, "fetch_role_details", details)
    semaphore = asyncio.Semaphore(hard_problems.DETAIL_CONCURRENCY)
    listings = [{"id": f"hard_problems:{i}", "url": f"{URL}-{i}", "description": "Summary"} for i in range(8)]
    results = await asyncio.gather(*(hard_problems._enrich_listing(None, semaphore, row) for row in listings))
    assert peak == hard_problems.DETAIL_CONCURRENCY
    assert [row["id"] for row in results] == [row["id"] for row in listings]
    assert all(row["sector"] == "Healthcare" and row["detail_status"] == "complete" for row in results)
