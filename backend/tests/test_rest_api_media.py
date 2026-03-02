# backend/tests/test_rest_api_media.py
#
# Integration tests for media-related app skills:
#   - news/search
#   - videos/search
#   - videos/get_transcript
#   - maps/search
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_media.py

import pytest


@pytest.mark.integration
def test_execute_skill_news_search(api_client):
    """
    Test executing the 'news/search' skill.
    Searches for recent AI news and validates the response structure.
    """
    payload = {
        "requests": [{"query": "artificial intelligence", "count": 3}]
    }

    print("\n[NEWS SEARCH] Searching for 'artificial intelligence' news...")
    response = api_client.post(
        "/v1/apps/news/skills/search", json=payload, timeout=30.0
    )
    assert response.status_code == 200, f"News search failed: {response.text}"

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "results" in first_group, "Result group should have 'results'"

    articles = first_group["results"]
    assert len(articles) > 0, "Expected at least one news article"

    article = articles[0]
    assert article.get("title"), "Article should have a 'title'"
    assert article.get("url"), "Article should have a 'url'"
    assert article.get("description"), "Article should have a 'description'"

    print(f"[NEWS SEARCH] Found {len(articles)} article(s)")
    print(f"[NEWS SEARCH] First title: {article.get('title')}")


@pytest.mark.integration
def test_execute_skill_maps_search(api_client):
    """
    Test executing the 'maps/search' skill.
    Searches for coffee shops in Munich and validates the response structure.
    """
    payload = {
        "requests": [{"query": "coffee shops in Munich", "pageSize": 3}]
    }

    print("\n[MAPS SEARCH] Searching for 'coffee shops in Munich'...")
    response = api_client.post(
        "/v1/apps/maps/skills/search", json=payload, timeout=30.0
    )
    assert response.status_code == 200, f"Maps search failed: {response.text}"

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "results" in first_group, "Result group should have 'results'"

    places = first_group["results"]
    assert len(places) > 0, "Expected at least one place result"

    place = places[0]
    assert place.get("name"), "Place should have a 'name'"
    assert place.get("formatted_address"), (
        "Place should have a 'formatted_address'"
    )

    print(f"[MAPS SEARCH] Found {len(places)} place(s)")
    print(
        f"[MAPS SEARCH] First place: {place.get('name')} - "
        f"{place.get('formatted_address')}"
    )


@pytest.mark.integration
def test_execute_skill_videos_search(api_client):
    """
    Test executing the 'videos/search' skill.
    Searches for Python tutorial videos and validates the response structure.
    """
    payload = {
        "requests": [
            {"query": "Python tutorial for beginners", "count": 3}
        ]
    }

    print(
        "\n[VIDEOS SEARCH] Searching for 'Python tutorial for beginners'..."
    )
    response = api_client.post(
        "/v1/apps/videos/skills/search", json=payload, timeout=30.0
    )
    assert response.status_code == 200, (
        f"Videos search failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "results" in first_group, "Result group should have 'results'"

    videos = first_group["results"]
    assert len(videos) > 0, "Expected at least one video result"

    video = videos[0]
    assert video.get("title"), "Video should have a 'title'"
    assert video.get("url"), "Video should have a 'url'"

    print(f"[VIDEOS SEARCH] Found {len(videos)} video(s)")
    print(f"[VIDEOS SEARCH] First video: {video.get('title')}")


@pytest.mark.integration
def test_execute_skill_videos_transcript(api_client):
    """
    Test executing the 'videos/get_transcript' skill.
    Fetches transcript for a short TED talk.

    NOTE: Sanitization may block videos whose transcripts contain code-like
    content. The test accepts this as a valid response (success=True but
    empty results with sanitization error) and checks it gracefully.
    """
    youtube_url = "https://www.youtube.com/watch?v=UF8uR6Z6KLc"

    payload = {"requests": [{"url": youtube_url, "languages": ["en"]}]}

    print(
        f"\n[VIDEOS TRANSCRIPT] Fetching transcript for: {youtube_url}"
    )
    response = api_client.post(
        "/v1/apps/videos/skills/get_transcript", json=payload, timeout=30.0
    )
    assert response.status_code == 200, (
        f"Videos transcript failed: {response.text}"
    )

    data = response.json()
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    first_group = results[0]
    assert "id" in first_group, "Result group should have 'id'"
    assert "results" in first_group, "Result group should have 'results'"

    transcripts = first_group.get("results", [])
    sanitization_error = first_group.get("error", "")

    if transcripts:
        transcript = transcripts[0]
        assert transcript.get("url") or transcript.get("video_id"), (
            "Transcript should reference the video"
        )
        transcript_text = (
            transcript.get("transcript")
            or transcript.get("text")
            or transcript.get("content", "")
        )
        assert len(transcript_text) > 100, (
            f"Transcript content too short: {len(transcript_text)} chars"
        )
        print(
            f"[VIDEOS TRANSCRIPT] Transcript length: "
            f"{len(transcript_text)} chars"
        )
        print(f"[VIDEOS TRANSCRIPT] Preview: {transcript_text[:200]}")
    else:
        assert sanitization_error, (
            "Empty results should include an error message"
        )
        print(
            f"[VIDEOS TRANSCRIPT] Sanitization blocked transcript "
            f"(expected behavior): {sanitization_error}"
        )
        print(
            "[VIDEOS TRANSCRIPT] NOTE: This is valid behavior - "
            "content sanitizer protects against prompt injection"
        )

    print("[VIDEOS TRANSCRIPT] PASSED - skill response structure is valid")
