# backend/tests/test_app_skills.py
#
# Unit tests for all app skills.
# Tests both single and multi-request scenarios for each skill.
#
# OPE-342: These tests previously HTTP-curled into per-app `app-{id}` containers
# (e.g. http://app-web:8000/skills/search). Those containers no longer exist —
# every skill now runs in-process inside `api`. The whole module is skipped
# until it is rewritten to either:
#   (a) hit the public REST endpoint POST /v1/apps/{id}/skills/{name} with an
#       API key (proper integration shape), or
#   (b) call get_global_registry().dispatch_skill(...) directly inside a
#       running `api` container via docker exec.
# Pick whichever fits the existing test infrastructure better.

import json
import subprocess
from pathlib import Path
from typing import Dict, Any
import pytest

pytestmark = pytest.mark.skip(
    reason="OPE-342: per-app containers removed; needs rewrite to use REST API or in-process registry"
)

# Test results directory (gitignored)
TEST_RESULTS_DIR = Path(__file__).parent.parent.parent / "test_results"
TEST_RESULTS_DIR.mkdir(exist_ok=True)


def docker_exec_curl(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a curl command via docker exec to call an API endpoint.
    
    Args:
        endpoint: The API endpoint (e.g., "http://app-web:8000/skills/search")
        data: The request payload as a dictionary
    
    Returns:
        The response JSON as a dictionary
    """
    json_data = json.dumps(data)
    cmd = [
        "docker", "exec", "api", "sh", "-c",
        f"curl -X POST {endpoint} -H 'Content-Type: application/json' -d '{json_data}'"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=60  # 60 second timeout
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "Request timeout"}
    except subprocess.CalledProcessError as e:
        return {"error": f"Command failed: {e.stderr}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response: {e}"}


def save_test_result(skill_name: str, test_name: str, request_data: Dict[str, Any], response_data: Dict[str, Any]):
    """
    Save test result to a JSON file for manual inspection.
    
    Args:
        skill_name: Name of the skill being tested
        test_name: Name of the test (e.g., "single_request", "multi_request")
        request_data: The request payload
        response_data: The response data
    """
    filename = f"{skill_name}_{test_name}.json"
    filepath = TEST_RESULTS_DIR / filename
    
    result = {
        "skill": skill_name,
        "test": test_name,
        "request": request_data,
        "response": response_data
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Test result saved to: {filepath}")


# Web Search Skill Tests
@pytest.mark.integration
class TestWebSearchSkill:
    """Tests for web search skill."""
    
    def test_web_search_single_request(self):
        """Test web search with a single request."""
        endpoint = "http://app-web:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "python programming"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("web_search", "single_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
        assert "results" in response["results"][0]
        assert isinstance(response["results"][0]["results"], list)
    
    def test_web_search_multi_request(self):
        """Test web search with multiple requests."""
        endpoint = "http://app-web:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "iphone"},
                {"id": "2", "query": "android"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("web_search", "multi_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 2
        
        # Verify each result has the correct id
        result_ids = {r["id"] for r in response["results"]}
        assert result_ids == {"1", "2"}
        
        # Verify each result has a results array
        for result in response["results"]:
            assert "results" in result
            assert isinstance(result["results"], list)


# News Search Skill Tests
@pytest.mark.integration
class TestNewsSearchSkill:
    """Tests for news search skill."""
    
    def test_news_search_single_request(self):
        """Test news search with a single request."""
        endpoint = "http://app-news:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "technology news"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("news_search", "single_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
    
    def test_news_search_multi_request(self):
        """Test news search with multiple requests."""
        endpoint = "http://app-news:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "AI news"},
                {"id": "2", "query": "climate change"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("news_search", "multi_request", request_data, response)
        
        assert "results" in response
        assert len(response["results"]) == 2


# Maps Search Skill Tests
@pytest.mark.integration
class TestMapsSearchSkill:
    """Tests for maps search skill."""
    
    def test_maps_search_single_request(self):
        """Test maps search with a single request."""
        endpoint = "http://app-maps:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "coffee shops in Berlin"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("maps_search", "single_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
    
    def test_maps_search_multi_request(self):
        """Test maps search with multiple requests."""
        endpoint = "http://app-maps:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "restaurants in Paris"},
                {"id": "2", "query": "museums in London"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("maps_search", "multi_request", request_data, response)
        
        assert "results" in response
        assert len(response["results"]) == 2


# Videos Search Skill Tests
@pytest.mark.integration
class TestVideosSearchSkill:
    """Tests for videos search skill."""
    
    def test_videos_search_single_request(self):
        """Test videos search with a single request."""
        endpoint = "http://app-videos:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "python tutorial"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("videos_search", "single_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
    
    def test_videos_search_multi_request(self):
        """Test videos search with multiple requests."""
        endpoint = "http://app-videos:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "machine learning"},
                {"id": "2", "query": "web development"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("videos_search", "multi_request", request_data, response)
        
        assert "results" in response
        assert len(response["results"]) == 2


# Web Read Skill Tests
@pytest.mark.integration
class TestWebReadSkill:
    """Tests for web read skill."""
    
    def test_web_read_single_request(self):
        """Test web read with a single request."""
        endpoint = "http://app-web:8000/skills/read"
        request_data = {
            "requests": [
                {"id": "1", "url": "https://www.tagesschau.de/inland/innenpolitik/haushalt-2026-beschlossen-100.html"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("web_read", "single_request", request_data, response)
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
    
    def test_web_read_multi_request(self):
        """Test web read with multiple requests."""
        endpoint = "http://app-web:8000/skills/read"
        request_data = {
            "requests": [
                {"id": "1", "url": "https://www.tagesschau.de/inland/innenpolitik/haushalt-2026-beschlossen-100.html"},
                {"id": "2", "url": "https://www.theverge.com/report/829137/openai-chatgpt-time-date"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("web_read", "multi_request", request_data, response)
        
        assert "results" in response
        assert len(response["results"]) == 2


# Video Transcript Skill Tests
@pytest.mark.integration
class TestVideoTranscriptSkill:
    """Tests for video transcript skill."""
    
    def test_video_transcript_single_request(self):
        """Test video transcript with a single request."""
        endpoint = "http://app-videos:8000/skills/get_transcript"
        # Using a known YouTube video ID for testing
        request_data = {
            "requests": [
                {"id": "1", "url": "https://www.youtube.com/watch?v=9hv4nr_46Ao"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("video_transcript", "single_request", request_data, response)
        
        # Check for errors first - if there's an error, the test should fail
        assert "error" not in response or response.get("error") is None, f"Transcript request failed with error: {response.get('error')}"
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == "1"
        
        # Verify that results are not empty (transcript was actually fetched)
        assert "results" in response["results"][0]
        assert isinstance(response["results"][0]["results"], list)
        assert len(response["results"][0]["results"]) > 0, "Transcript result should not be empty"
        
        # Verify transcript result has required fields
        transcript_result = response["results"][0]["results"][0]
        assert "url" in transcript_result
        assert "transcript" in transcript_result
        assert transcript_result["transcript"] is not None, "Transcript text should not be None"
    
    def test_video_transcript_multi_request(self):
        """Test video transcript with multiple requests."""
        endpoint = "http://app-videos:8000/skills/get_transcript"
        request_data = {
            "requests": [
                {"id": "1", "url": "https://www.youtube.com/watch?v=8eqdMpCz9tc"},
                {"id": "2", "url": "https://www.youtube.com/watch?v=Dl3Olh29_nY"}
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("video_transcript", "multi_request", request_data, response)
        
        # Check for errors first - if there's an error, the test should fail
        assert "error" not in response or response.get("error") is None, f"Transcript request failed with error: {response.get('error')}"
        
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 2
        
        # Verify each result has the correct id
        result_ids = {r["id"] for r in response["results"]}
        assert result_ids == {"1", "2"}
        
        # Verify each result has a results array and is not empty
        for result in response["results"]:
            assert "results" in result
            assert isinstance(result["results"], list)
            assert len(result["results"]) > 0, f"Transcript result for id {result['id']} should not be empty"
            
            # Verify transcript result has required fields
            transcript_result = result["results"][0]
            assert "url" in transcript_result
            assert "transcript" in transcript_result
            assert transcript_result["transcript"] is not None, f"Transcript text for id {result['id']} should not be None"


# Validation Tests
@pytest.mark.integration
class TestSkillValidation:
    """Tests for request validation (id field, etc.)."""
    
    def test_web_search_single_request_id_optional(self):
        """Test that single request without id field succeeds (id is auto-generated)."""
        endpoint = "http://app-web:8000/skills/search"
        request_data = {
            "requests": [
                {"query": "atopile"}  # Missing id - should be auto-generated for single requests
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        save_test_result("web_search", "single_request_no_id", request_data, response)
        
        # Should succeed - id is optional for single requests
        assert "results" in response
        assert isinstance(response["results"], list)
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == 1  # Auto-generated id
        assert "results" in response["results"][0]
    
    def test_web_search_multi_request_missing_id(self):
        """Test that a missing id in a multi-request call is auto-generated (not an error).

        The BaseSkill contract (documented in _validate_and_normalize_request_id) states
        that 'id' is always optional and auto-generates a sequential integer when absent.
        A request without 'id' must succeed and the auto-generated id must appear in results.
        Previously this test incorrectly expected a validation error; the real invariant
        to guard is that the response has the correct number of result groups.
        """
        endpoint = "http://app-web:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "vscode"},
                {"query": "cursor"}  # Missing id — auto-generated as 2
            ]
        }

        response = docker_exec_curl(endpoint, request_data)

        # Should succeed: missing id is auto-filled, not rejected
        assert "results" in response, (
            f"Expected 'results' in response but got: {response}"
        )
        assert len(response["results"]) == 2, (
            f"Expected 2 result groups but got {len(response['results'])}: {response}"
        )
        result_ids = {str(r["id"]) for r in response["results"]}
        assert "1" in result_ids, (
            f"Expected explicit id '1' in results, got: {result_ids}"
        )
        # The second request had no id — auto-generated id should be present (as int 2 or str "2")
        assert "2" in result_ids or 2 in {r["id"] for r in response["results"]}, (
            f"Expected auto-generated id 2 in results, got: {result_ids}"
        )
    
    def test_web_search_duplicate_id(self):
        """Test that duplicate ids return an error."""
        endpoint = "http://app-web:8000/skills/search"
        request_data = {
            "requests": [
                {"id": "1", "query": "vscode"},
                {"id": "1", "query": "cursor"}  # Duplicate id
            ]
        }
        
        response = docker_exec_curl(endpoint, request_data)
        
        assert "error" in response
        assert "duplicate" in response["error"].lower()

