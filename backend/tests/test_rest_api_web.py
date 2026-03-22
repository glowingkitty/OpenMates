# backend/tests/test_rest_api_web.py
#
# Integration tests for web app skills:
#   - web/search
#   - web/read
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_web.py

import pytest


@pytest.mark.integration
def test_execute_skill_web_search(api_client):
    """Test executing the 'web/search' skill."""
    payload = {"requests": [{"query": "OpenMates", "count": 1}]}
    response = api_client.post("/v1/apps/web/skills/search", json=payload)
    assert response.status_code == 200, f"Web search failed: {response.text}"

    data = response.json()
    assert data["success"] is True
    assert "data" in data
    assert "results" in data["data"]


@pytest.mark.integration
def test_execute_skill_web_read(api_client):
    """
    Test executing the 'web/read' skill.
    Reads a stable, publicly accessible URL and validates the response structure.
    """
    payload = {"requests": [{"url": "https://example.com"}]}

    print("\n[WEB READ] Reading https://example.com...")
    response = api_client.post(
        "/v1/apps/web/skills/read", json=payload, timeout=30.0
    )
    assert response.status_code == 200, f"Web read failed: {response.text}"

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data, "Response missing 'results'"

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "id" in first_group, "Result group should have 'id'"
    assert "results" in first_group, "Result group should have 'results'"

    pages = first_group["results"]
    assert len(pages) > 0, "Expected at least one page result"

    page = pages[0]
    assert page.get("url"), "Page result should have a 'url'"
    assert "title" in page, "Page result should have a 'title'"
    assert "markdown" in page, "Page result should have 'markdown' content"
    assert len(page.get("markdown", "")) > 0, (
        "Markdown content should not be empty"
    )

    print(f"[WEB READ] Title: {page.get('title')}")
    print(f"[WEB READ] Markdown length: {len(page.get('markdown', ''))} chars")
