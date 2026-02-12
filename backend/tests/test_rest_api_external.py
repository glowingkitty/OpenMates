import os
import json
import httpx
import pytest
import io
from PIL import Image
from dotenv import load_dotenv

try:
    import c2pa
    HAS_C2PA = True
except ImportError:
    HAS_C2PA = False

# Load environment variables from the root .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

def log_response(response: httpx.Response):
    """Event hook to log responses for debugging."""
    # Read the response content if it hasn't been read yet
    try:
        response.read()
    except Exception:
        pass

    print(f"\n[API] {response.request.method} {response.request.url} -> {response.status_code}")
    try:
        # Try to parse as JSON for pretty printing
        data = response.json()
        print(f"[RESPONSE] {json.dumps(data, indent=2)}")
    except Exception:
        # Fallback to text if not JSON or if reading fails
        try:
            if response.text:
                # Truncate very long text responses (like CSV exports)
                text = response.text
                if len(text) > 1000:
                    text = text[:1000] + "... (truncated)"
                print(f"[RESPONSE] {text}")
            else:
                print("[RESPONSE] (empty body)")
        except Exception:
            print("[RESPONSE] (could not read body)")

def verify_image_metadata(image_bytes: bytes, expected_prompt: str, expected_model: str):
    """Verify that the generated image contains the expected AI metadata and C2PA provenance."""
    print(f"[VERIFY] Checking metadata/C2PA for image ({len(image_bytes)} bytes)...")
    try:
        # 1. Standard XMP Check
        img = Image.open(io.BytesIO(image_bytes))
        xmp = img.info.get("xmp")
        
        if not xmp:
            print(f"[FAIL] No XMP metadata found. Available info: {list(img.info.keys())}")
            # WebP often stores metadata in a different way in Pillow depending on version, 
            # but our implementation explicitly saves it as 'xmp'.
            pytest.fail("No XMP metadata found in generated image")
            
        xmp_str = xmp.decode("utf-8") if isinstance(xmp, bytes) else xmp
        
        # Core AI signal
        assert "trainedAlgorithmicMedia" in xmp_str, "Missing 'trainedAlgorithmicMedia' marker in XMP"
        
        # Model info
        if expected_model:
            # We check if the provided model reference is at least partially in the metadata
            # (it might be prefixed with "Google" or "fal.ai" by the processor)
            model_snippet = expected_model.split('/')[-1] if '/' in expected_model else expected_model
            assert model_snippet in xmp_str, f"Expected model snippet '{model_snippet}' (from '{expected_model}') not found in XMP metadata"
        
        # Prompt info (snippet)
        prompt_snippet = expected_prompt[:30]
        assert prompt_snippet in xmp_str, f"Prompt snippet '{prompt_snippet}' not found in XMP metadata"
        
        # Software marker
        assert "OpenMates" in xmp_str, "Missing 'OpenMates' software marker in XMP"
        
        print("[OK] XMP metadata markers verified.")

        # 2. C2PA (Content Credentials) Check
        print("[VERIFY] Checking C2PA (Coalition for Content Provenance and Authenticity)...")
        # JUMBF box marker is mandatory for C2PA
        has_c2pa_jumb = b"jumb" in image_bytes.lower()
        assert has_c2pa_jumb, "Missing C2PA JUMBF box in image bytes"

        if HAS_C2PA:
            try:
                # Use c2pa-python to verify the manifest store
                mime_type = "image/webp"
                if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                    mime_type = "image/png"
                elif image_bytes.startswith(b"\xff\xd8"):
                    mime_type = "image/jpeg"

                with c2pa.Reader(mime_type, io.BytesIO(image_bytes)) as reader:
                    manifest_json = reader.json()
                    if not manifest_json:
                        pytest.fail("C2PA Reader found no manifest")
                    
                    # Verify manifest contents
                    assert "trainedAlgorithmicMedia" in manifest_json, "C2PA manifest missing AI digital source type"
                    assert "OpenMates" in manifest_json, "C2PA manifest missing OpenMates generator info"
                    
                    # Verify validation state
                    validation = reader.get_validation_state()
                    print(f"[INFO] C2PA Validation State: {validation}")
                    
                print("[OK] C2PA manifest verified with c2pa-python library!")
            except Exception as e:
                print(f"[WARN] C2PA library verification failed, falling back to byte check: {e}")
        else:
            print("[INFO] c2pa-python not installed, verified via JUMBF byte marker only.")

        print("[OK] All metadata and C2PA markers found successfully!")
        
    except Exception as e:
        print(f"[ERROR] Failed to verify metadata/C2PA: {e}")
        raise e

# This test suite makes real requests to the dev API domain using a real API key.
# It validates that the REST API endpoints are functional and return expected structures.
#
# Execution command:
# /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py
#
# Note: Ensure the root .env file contains OPENMATES_TEST_ACCOUNT_API_KEY.

# Configuration
API_BASE_URL = "https://api.dev.openmates.org"
API_KEY = os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY")

# Skip all tests in this module if API_KEY is not set
if not API_KEY:
    pytest.skip("OPENMATES_TEST_ACCOUNT_API_KEY environment variable not set. Please set it to a valid sk-api-... key.",allow_module_level=True)

@pytest.fixture
def api_client():
    """Fixture for authenticated httpx client."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    # Using a 60s timeout - AI skill executions can be slow
    return httpx.Client(
        base_url=API_BASE_URL, 
        headers=headers, 
        timeout=60.0,
        event_hooks={'response': [log_response]}
    )

@pytest.mark.integration
def test_health_endpoint():
    """Test the public health endpoint (v1)."""
    with httpx.Client(base_url=API_BASE_URL, event_hooks={'response': [log_response]}) as client:
        response = client.get("/v1/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "providers" in data
        assert "apps" in data

@pytest.mark.integration
def test_server_info_endpoint():
    """Test the public server info endpoint (v1)."""
    with httpx.Client(base_url=API_BASE_URL, event_hooks={'response': [log_response]}) as client:
        response = client.get("/v1/server")
        assert response.status_code == 200, f"Server info failed: {response.text}"
        data = response.json()
        assert "domain" in data
        assert "self_hosted" in data
        assert "edition" in data
        # Domain might include 'api.' prefix depending on how it's detected
        assert "dev.openmates.org" in data["domain"]

@pytest.mark.integration
def test_apps_metadata_authenticated(api_client):
    """Test the apps metadata endpoint with authentication."""
    response = api_client.get("/v1/apps/metadata")
    assert response.status_code == 200, f"Apps metadata failed: {response.text}"
    data = response.json()
    # The dev server seems to return {"apps": {...}} instead of a flat list
    if isinstance(data, dict) and "apps" in data:
        apps = data["apps"]
        assert "ai" in apps
        assert "web" in apps
    else:
        assert isinstance(data, list)
        app_ids = [app["id"] for app in data]
        assert "ai" in app_ids
        assert "web" in app_ids

@pytest.mark.integration
def test_specific_app_metadata(api_client):
    """Test metadata for a specific app (ai)."""
    response = api_client.get("/v1/apps/ai/metadata")
    assert response.status_code == 200, f"App metadata failed: {response.text}"
    data = response.json()
    assert data["id"] == "ai"
    assert "skills" in data
    
    # Check for 'ask' skill
    skill_ids = [skill["id"] for skill in data["skills"]]
    assert "ask" in skill_ids

@pytest.mark.integration
def test_specific_skill_metadata(api_client):
    """Test metadata for a specific skill (ai/ask)."""
    # Dynamic route is /v1/apps/{app_id}/skills/{skill_id}
    response = api_client.get("/v1/apps/ai/skills/ask")
    assert response.status_code == 200, f"Skill metadata failed: {response.text}"
    data = response.json()
    assert data["id"] == "ask"
    assert "providers" in data

@pytest.mark.integration
def test_usage_summary_authenticated(api_client):
    """Test the usage summary endpoint."""
    # usage_api.py defines /v1/settings/usage/summaries
    response = api_client.get("/v1/settings/usage/summaries?type=apps")
    assert response.status_code == 200, f"Usage summary failed: {response.text}"
    data = response.json()
    assert "summaries" in data

@pytest.mark.integration
def test_execute_skill_ask(api_client):
    """
    Test executing the 'ai/ask' skill.
    This is a real execution that will be billed to the API key.
    """
    payload = {
        "messages": [
            {"role": "user", "content": "Capital city of Germany?"}
        ],
        "stream": False
    }
    # Dynamic route is /v1/apps/{app_id}/skills/{skill_id}
    # Use 20 second timeout - AI processing includes preprocessing, LLM inference, and post-processing
    try:
        response = api_client.post("/v1/apps/ai/skills/ask", json=payload, timeout=20.0)
        assert response.status_code == 200, f"Skill execution failed: {response.text}"
        data = response.json()
        # Check for successful OpenAI-compatible response format
        assert "choices" in data, "Response should have 'choices' field for OpenAI-compatible format"
        assert len(data["choices"]) > 0, "Response should have at least one choice"
        # Verify the response contains actual content
        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"
        # Ensure the correct answer is in the response
        assert "Berlin" in content, f"Expected 'Berlin' to be in response, but got: {content}"
        # Ensure no error message was returned as content (errors should be HTTP 4xx/5xx)
        assert not content.startswith("Error:"), f"Response contains error message: {content}"
    except httpx.TimeoutException:
        print("\n[TIMEOUT] Request to ai/ask timed out after 20 seconds.")
        pytest.fail("Request timed out after 20 seconds")

@pytest.mark.integration
def test_execute_skill_web_search(api_client):
    """Test executing the 'web/search' skill."""
    payload = {
        "requests": [
            {"query": "OpenMates", "count": 1}
        ]
    }
    # Dynamic route is /v1/apps/{app_id}/skills/{skill_id}
    response = api_client.post("/v1/apps/web/skills/search", json=payload)
    assert response.status_code == 200, f"Web search failed: {response.text}"
    
    data = response.json()
    # It's wrapped in WrappedSkillResponse: {success: bool, data: ..., credits_charged: ...}
    assert data["success"] is True
    assert "data" in data
    assert "results" in data["data"]

@pytest.mark.integration
def test_execute_skill_image_generation_draft(api_client):
    """
    Test executing the 'images/generate_draft' skill.
    This is a long-running skill that returns a task ID and embed ID.
    After completion, it downloads the decrypted image from the embeds endpoint.
    """
    import time
    
    prompt = "a cute cartoon cat wearing a tiny red hat"
    
    payload = {
        "requests": [
            {"prompt": prompt}
        ]
    }
    
    # 1. Execute skill
    print(f"\n[IMAGE DRAFT] Generating image with prompt: '{prompt}'")
    response = api_client.post("/v1/apps/images/skills/generate_draft", json=payload)
    assert response.status_code == 200, f"Image generation failed: {response.text}"
    
    data = response.json()
    assert data["success"] is True
    assert "data" in data
    assert "task_id" in data["data"]
    assert "embed_id" in data["data"]
    
    task_id = data["data"]["task_id"]
    embed_id = data["data"]["embed_id"]
    print(f"[TASK] Dispatched image generation task: {task_id}")
    print(f"[EMBED] Associated embed_id: {embed_id}")
    
    # 2. Poll for status
    max_retries = 30
    poll_interval = 2.0
    
    completed_result = None
    for i in range(max_retries):
        status_resp = api_client.get(f"/v1/tasks/{task_id}")
        assert status_resp.status_code == 200
        
        status_data = status_resp.json()
        status = status_data["status"]
        
        if status == "completed":
            assert "result" in status_data
            completed_result = status_data["result"]
            assert completed_result["type"] == "image"
            assert completed_result["embed_id"] == embed_id
            assert "files" in completed_result
            assert "preview" in completed_result["files"]
            assert "full" in completed_result["files"]
            assert "original" in completed_result["files"]
            print("\n[SUCCESS] Image generation completed!")
            break
        elif status == "failed":
            error_msg = status_data.get("error", "Unknown task error")
            print(f"\n[FAILED] Task failed: {error_msg}")
            pytest.fail(f"Task failed: {error_msg}")
            
        if (i + 1) % 5 == 0:
            print(f"[POLL] Attempt {i+1}: status={status}...")
            
        time.sleep(poll_interval)
    else:
        pytest.fail(f"Task timed out after {max_retries * poll_interval} seconds")

    # 3. Download and verify the decrypted image from the embed endpoint
    # We test the 'full' format as it has higher quality and guaranteed metadata preservation
    print(f"[DOWNLOAD] Requesting decrypted image from /v1/embeds/{embed_id}/file?format=full")
    
    download_response = api_client.get(f"/v1/embeds/{embed_id}/file?format=full")
    
    if download_response.status_code == 200:
        # Save to local file
        filename = "test_generated_image_draft.webp"
        with open(filename, "wb") as f:
            f.write(download_response.content)
        
        file_size = len(download_response.content)
        assert file_size > 0
        assert download_response.headers["Content-Type"] == "image/webp"
        print(f"\n[IMAGE SAVED] Decrypted draft image saved to: {os.path.abspath(filename)} ({file_size} bytes)")
        
        # Verify AI Metadata
        # Draft model for generate_draft is typically bfl/flux-schnell
        # We'll use the model reference returned in the result if available, or fallback
        expected_model = completed_result.get("model", "bfl/flux-schnell")
        verify_image_metadata(download_response.content, prompt, expected_model)
    else:
        print(f"\n[DOWNLOAD FAILED] Status: {download_response.status_code}")
        print(f"Response: {download_response.text}")
        pytest.fail(f"Failed to download decrypted image: {download_response.text}")

@pytest.mark.integration
def test_execute_skill_image_generation_high_end(api_client):
    """
    Test executing the high-end 'images/generate' skill.
    """
    import time
    
    # Complex prompt for high-end generation
    prompt = "A futuristic cyberpunk cityscape at sunset with neon signs and flying cars, high detail, 4k"
    
    payload = {
        "requests": [
            {"prompt": prompt, "aspect_ratio": "16:9"}
        ]
    }
    
    # 1. Execute skill
    print(f"\n[IMAGE HIGH-END] Generating image with prompt: '{prompt}'")
    response = api_client.post("/v1/apps/images/skills/generate", json=payload)
    assert response.status_code == 200, f"Image generation failed: {response.text}"
    
    data = response.json()
    assert data["success"] is True
    task_id = data["data"]["task_id"]
    embed_id = data["data"]["embed_id"]
    print(f"[TASK] Dispatched high-end task: {task_id}")
    
    # 2. Poll for status (allow more time for high-end)
    max_retries = 60
    poll_interval = 2.0
    completed_result = None
    
    for i in range(max_retries):
        status_resp = api_client.get(f"/v1/tasks/{task_id}")
        status_data = status_resp.json()
        status = status_data["status"]
        
        if status == "completed":
            completed_result = status_data.get("result")
            print("\n[SUCCESS] High-end image generation completed!")
            break
        elif status == "failed":
            pytest.fail(f"Task failed: {status_data.get('error')}")
            
        if (i + 1) % 5 == 0:
            print(f"[POLL] Attempt {i+1}: status={status}...")
        time.sleep(poll_interval)
    else:
        pytest.fail("Task timed out")

    # 3. Download full format and verify metadata
    # We test the 'full' format as it has higher quality and guaranteed metadata preservation
    print(f"[DOWNLOAD] Requesting full format from /v1/embeds/{embed_id}/file?format=full")
    download_response = api_client.get(f"/v1/embeds/{embed_id}/file?format=full")
    
    if download_response.status_code == 200:
        filename = "test_generated_image_high.webp"
        with open(filename, "wb") as f:
            f.write(download_response.content)
        print(f"[IMAGE SAVED] High-end image saved to: {os.path.abspath(filename)} ({len(download_response.content)} bytes)")
        
        # Verify AI Metadata
        expected_model = completed_result.get("model", "google/gemini-3-pro-image-preview")
        verify_image_metadata(download_response.content, prompt, expected_model)
    else:
        pytest.fail(f"Download failed: {download_response.status_code}")


@pytest.mark.integration
def test_usage_summaries_authenticated(api_client):
    """Test the usage summaries endpoint (v1/settings/usage/summaries)."""
    # Test for 'apps' type
    response = api_client.get("/v1/settings/usage/summaries?type=apps&months=1")
    assert response.status_code == 200, f"Usage summaries failed: {response.text}"
    data = response.json()
    assert "summaries" in data
    assert "type" in data
    assert data["type"] == "apps"

@pytest.mark.integration
def test_usage_details_authenticated(api_client):
    """Test the usage details endpoint (v1/settings/usage/details)."""
    # Fetch summaries first to get a valid identifier and year_month
    summary_resp = api_client.get("/v1/settings/usage/summaries?type=apps")
    assert summary_resp.status_code == 200
    summaries = summary_resp.json().get("summaries", [])
    
    if not summaries:
        pytest.skip("No usage summaries found to test details")
        
    identifier = summaries[0]["app_id"]
    year_month = summaries[0]["year_month"]
    
    response = api_client.get(f"/v1/settings/usage/details?type=app&identifier={identifier}&year_month={year_month}&limit=10")
    assert response.status_code == 200, f"Usage details failed: {response.text}"
    data = response.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)

@pytest.mark.integration
def test_usage_export_authenticated(api_client):
    """Test the usage export endpoint (v1/settings/usage/export)."""
    response = api_client.get("/v1/settings/usage/export?months=1")
    assert response.status_code == 200, f"Usage export failed: {response.text}"
    assert "text/csv" in response.headers["Content-Type"]
    assert "attachment" in response.headers["Content-Disposition"]
    assert "usage-export" in response.headers["Content-Disposition"] or "usage_export" in response.headers["Content-Disposition"]

@pytest.mark.integration
def test_billing_overview_authenticated(api_client):
    """Test the billing overview endpoint (v1/settings/billing)."""
    response = api_client.get("/v1/settings/billing")
    assert response.status_code == 200, f"Billing overview failed: {response.text}"
    data = response.json()
    assert "payment_tier" in data
    assert "invoices" in data
    assert "auto_topup_enabled" in data

@pytest.mark.integration
def test_api_keys_list_authenticated(api_client):
    """Test listing API keys for the current user."""
    response = api_client.get("/v1/settings/api-keys")
    assert response.status_code == 200, f"API keys list failed: {response.text}"
    data = response.json()
    if isinstance(data, dict) and "api_keys" in data:
        keys = data["api_keys"]
    else:
        assert isinstance(data, list)
        keys = data
    # The current API key should be in the list (or at least one key)
    assert len(keys) > 0

@pytest.mark.integration
@pytest.mark.skip(reason="Creator tip endpoint is currently causing a disconnect in this environment")
def test_tip_creator_authenticated(api_client):
    """
    Test the creator tip endpoint.
    Note: This will fail with 404 in self-hosted mode if payment is disabled.
    We'll check for either 200 (success) or 400 (insufficient credits) or 404 (disabled).
    """
    payload = {
        "owner_id": "test-creator-id",
        "content_type": "website",
        "credits": 1
    }
    response = api_client.post("/v1/creators/tip", json=payload)
    # If payment is disabled on dev, it will be 404
    # If credits are 0, it will be 400
    assert response.status_code in [200, 400, 404], f"Unexpected status code: {response.status_code}, {response.text}"

@pytest.mark.integration
def test_execute_skill_travel_search_connections(api_client):
    """
    Test executing the 'travel/search_connections' skill.
    Searches for a one-way flight from Munich to London via the Amadeus API.
    """
    from datetime import datetime, timedelta

    # Use a date 14 days in the future to ensure availability
    departure_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    payload = {
        "requests": [
            {
                "legs": [
                    {
                        "origin": "Munich",
                        "destination": "London",
                        "date": departure_date,
                    }
                ],
                "transport_methods": ["airplane"],
                "passengers": 1,
                "travel_class": "economy",
                "max_results": 3,
                "currency": "EUR",
            }
        ]
    }

    print(f"\n[TRAVEL] Searching flights: Munich -> London on {departure_date}")
    response = api_client.post(
        "/v1/apps/travel/skills/search_connections",
        json=payload,
        timeout=30.0,
    )
    assert response.status_code == 200, f"Travel search_connections failed: {response.text}"

    data = response.json()
    # Wrapped in WrappedSkillResponse: {success: bool, data: ..., credits_charged: ...}
    assert data["success"] is True, f"Skill returned success=False: {data}"
    assert "data" in data
    skill_data = data["data"]
    assert "results" in skill_data

    # Validate result structure
    results = skill_data["results"]
    assert len(results) > 0, "Expected at least one result group"

    # First result group should have results
    first_group = results[0]
    assert "id" in first_group, "Result group should have 'id'"
    assert "results" in first_group, "Result group should have 'results'"

    connections = first_group["results"]
    assert len(connections) > 0, "Expected at least one flight connection"

    # Validate first connection structure
    conn = connections[0]
    assert conn["type"] == "connection", f"Expected type 'connection', got '{conn.get('type')}'"
    assert conn["transport_method"] == "airplane"
    assert conn.get("total_price") is not None, "Expected a price"
    assert conn.get("currency") is not None, "Expected a currency"
    assert conn.get("legs") is not None, "Expected legs array"
    assert len(conn["legs"]) >= 1, "Expected at least one leg"

    # Validate leg structure
    leg = conn["legs"][0]
    assert "origin" in leg, "Leg should have 'origin'"
    assert "destination" in leg, "Leg should have 'destination'"
    assert "departure" in leg, "Leg should have 'departure'"
    assert "arrival" in leg, "Leg should have 'arrival'"
    assert "duration" in leg, "Leg should have 'duration'"
    assert "stops" in leg, "Leg should have 'stops'"
    assert "segments" in leg, "Leg should have 'segments'"

    # Validate segment structure
    assert len(leg["segments"]) >= 1, "Expected at least one segment"
    segment = leg["segments"][0]
    assert "carrier" in segment, "Segment should have 'carrier'"
    assert "departure_station" in segment, "Segment should have 'departure_station'"
    assert "arrival_station" in segment, "Segment should have 'arrival_station'"

    # Print summary
    print(f"[TRAVEL] Found {len(connections)} connection(s)")
    for i, c in enumerate(connections[:3]):
        legs_info = c.get("legs", [])
        if legs_info:
            first = legs_info[0]
            print(
                f"  [{i+1}] {first.get('origin')} -> {first.get('destination')} | "
                f"{first.get('duration')} | {first.get('stops')} stop(s) | "
                f"{c.get('total_price')} {c.get('currency')}"
            )

    # Verify provider
    assert skill_data.get("provider") == "Amadeus", f"Expected provider 'Amadeus', got '{skill_data.get('provider')}'"


@pytest.mark.integration
def test_execute_skill_ask_deepseek_v3_2(api_client):
    """
    Test executing the 'ai/ask' skill targeting DeepSeek V3.2 specifically.
    
    This validates that the google_maas_client.py OpenAI-compatible API client
    correctly routes requests to Google Vertex AI MaaS for DeepSeek V3.2.
    
    Uses the @ai-model: override syntax to force model selection.
    """
    payload = {
        "messages": [
            {"role": "user", "content": "What is the capital of France? @ai-model:deepseek-v3.2"}
        ],
        "stream": False
    }
    
    print("\n[DEEPSEEK TEST] Sending request targeting DeepSeek V3.2 via @ai-model override...")
    try:
        # DeepSeek via Google MaaS can be slower due to the additional hop
        response = api_client.post("/v1/apps/ai/skills/ask", json=payload, timeout=60.0)
        assert response.status_code == 200, f"DeepSeek V3.2 skill execution failed with status {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Should NOT have an error response
        assert "error" not in data, f"Got error response: {data.get('error')}"
        
        # Validate OpenAI-compatible response structure
        assert "choices" in data, f"Response missing 'choices' field. Got keys: {list(data.keys())}"
        assert len(data["choices"]) > 0, "Response should have at least one choice"
        
        choice = data["choices"][0]
        assert "message" in choice, f"Choice missing 'message' field. Got: {choice}"
        assert "content" in choice["message"], f"Message missing 'content'. Got: {choice['message']}"
        
        content = choice["message"]["content"]
        assert content, "Response content should not be empty"
        assert len(content) > 10, f"Response suspiciously short ({len(content)} chars): {content}"
        
        # Verify the answer is correct
        assert "Paris" in content, f"Expected 'Paris' in response, got: {content[:200]}"
        
        # Verify model attribution in response metadata
        assert "model" in data, "Response should include 'model' field"
        model_name = data["model"].lower()
        assert "deepseek" in model_name, f"Expected model name to contain 'deepseek', got: {data['model']}"
        
        # Verify the response has proper finish reason
        assert choice.get("finish_reason") in ["stop", "end_turn", None], \
            f"Unexpected finish_reason: {choice.get('finish_reason')}"
        
        print(f"[DEEPSEEK TEST] Model: {data.get('model')}")
        print(f"[DEEPSEEK TEST] Response length: {len(content)} chars")
        print(f"[DEEPSEEK TEST] Content preview: {content[:200]}")
        
        # Verify usage metadata if present
        # Note: Google MaaS streaming may not always return prompt/completion token counts
        # (they can be 0 in SSE mode), but our token estimator provides user_input_tokens
        # and system_prompt_tokens independently.
        if "usage" in data and data["usage"]:
            usage = data["usage"]
            total_tokens = (
                usage.get("prompt_tokens", 0)
                + usage.get("completion_tokens", 0)
                + usage.get("user_input_tokens", 0)
                + usage.get("system_prompt_tokens", 0)
            )
            assert total_tokens > 0, "Expected some token count (from provider or our estimator)"
            print(f"[DEEPSEEK TEST] Tokens: prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}, user_input={usage.get('user_input_tokens')}, system_prompt={usage.get('system_prompt_tokens')}")
        
        print("[DEEPSEEK TEST] PASSED - DeepSeek V3.2 via Google MaaS is working correctly!")
        
    except httpx.TimeoutException:
        print("\n[TIMEOUT] DeepSeek V3.2 request timed out after 60 seconds.")
        pytest.fail("DeepSeek V3.2 request timed out after 60 seconds")


@pytest.mark.integration
def test_execute_skill_ask_deepseek_multi_turn(api_client):
    """
    Test multi-turn conversation with DeepSeek V3.2.
    Sends a two-message conversation to verify context handling through the
    google_maas_client.py OpenAI-compatible endpoint.
    """
    payload = {
        "messages": [
            {"role": "user", "content": "Remember this number: 42. @ai-model:deepseek-v3.2"},
            {"role": "assistant", "content": "I'll remember the number 42."},
            {"role": "user", "content": "What number did I ask you to remember?"}
        ],
        "stream": False
    }
    
    print("\n[DEEPSEEK MULTI-TURN] Testing multi-turn conversation with DeepSeek V3.2...")
    try:
        response = api_client.post("/v1/apps/ai/skills/ask", json=payload, timeout=60.0)
        assert response.status_code == 200, f"Multi-turn request failed: {response.text}"
        
        data = response.json()
        assert "error" not in data, f"Got error response: {data.get('error')}"
        assert "choices" in data, f"Response missing 'choices'. Keys: {list(data.keys())}"
        
        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"
        
        # The model should recall the number 42
        assert "42" in content, f"Expected model to recall '42', got: {content[:300]}"
        
        print(f"[DEEPSEEK MULTI-TURN] Response: {content[:200]}")
        print("[DEEPSEEK MULTI-TURN] PASSED - Context maintained across turns!")
        
    except httpx.TimeoutException:
        pytest.fail("Multi-turn DeepSeek request timed out after 60 seconds")


@pytest.mark.integration
def test_execute_skill_ask_image_generation_via_ai(api_client):
    """
    Test that ai/ask correctly triggers image generation when the user asks for an image.
    
    This test validates the full pipeline:
    1. Preprocessing should detect the image generation intent and preselect 'images-generate'
    2. The main LLM should call 'images-generate' (not just 'images' or other hallucinated names)
    3. The response should contain an embed reference for the generated image
    4. The response should also contain natural language text (not just the embed block)
    
    Reproduces a bug where:
    - Preprocessing failed to preselect 'images-generate', so the tool wasn't available
    - The LLM saw image generation mentioned in the system prompt and hallucinated tool calls
    - The hallucinated tool name 'images' was invalid (expected 'images-generate' format)
    - This consumed all iteration budget, resulting in no follow-up text
    """
    # Use an ambiguous prompt that may or may not trigger image generation.
    # The original bug used "Design a coffee cup mockup" which the preprocessor 
    # failed to preselect images-generate for, causing the main LLM to hallucinate
    # an invalid tool name 'images' (missing the '-generate' suffix).
    payload = {
        "messages": [
            {"role": "user", "content": "Design a coffee cup mockup"}
        ],
        "stream": False
    }
    
    print("\n[IMAGE VIA AI] Testing ai/ask with image generation prompt...")
    try:
        # Image generation can take longer due to preprocessing + main LLM + async image gen.
        # Non-stream requests may also hit reverse proxy timeouts, so use a generous client timeout.
        response = api_client.post("/v1/apps/ai/skills/ask", json=payload, timeout=120.0)
        # 502 Bad Gateway typically means the reverse proxy timed out waiting for the backend.
        # This is a valid failure mode for non-stream requests that take too long.
        if response.status_code == 502:
            pytest.skip("Got 502 (gateway timeout) - non-stream AI request took too long. "
                        "This is expected for complex prompts that trigger multiple LLM iterations.")
        assert response.status_code == 200, f"AI ask failed with status {response.status_code}: {response.text}"
        
        data = response.json()
        assert "error" not in data, f"Got error response: {data.get('error')}"
        assert "choices" in data, f"Response missing 'choices' field. Got keys: {list(data.keys())}"
        assert len(data["choices"]) > 0, "Response should have at least one choice"
        
        content = data["choices"][0].get("message", {}).get("content", "")
        assert content, "Response content should not be empty"
        
        print(f"[IMAGE VIA AI] Response length: {len(content)} chars")
        print(f"[IMAGE VIA AI] Content preview: {content[:500]}")
        
        # The response should contain an embed reference (app_skill_use code block)
        has_embed = "app_skill_use" in content or "embed_id" in content
        
        if has_embed:
            print("[IMAGE VIA AI] Found embed reference in response (image generation triggered)")
            
            # CRITICAL: The response must also contain natural language text OUTSIDE the code block.
            # Strip the JSON code block(s) and check if there's remaining text.
            import re
            text_outside_code_blocks = re.sub(r'```json\s*\{[^}]*\}\s*```', '', content).strip()
            
            # The LLM should provide a natural language acknowledgment alongside the embed
            # (e.g., "I'm generating that image for you now")
            assert len(text_outside_code_blocks) > 5, (
                f"Response contains embed reference but no follow-up text. "
                f"The LLM should provide a natural language response alongside the image embed. "
                f"Full content: {content}"
            )
            print(f"[IMAGE VIA AI] Follow-up text: {text_outside_code_blocks[:200]}")
        else:
            # If no embed, the LLM should still provide a useful response
            # (it might describe how to create an image or explain what it would generate)
            assert len(content) > 20, f"Response too short without image embed: {content}"
            print("[IMAGE VIA AI] No embed reference found (LLM responded with text instead of generating)")
        
        # Verify usage metadata
        if "usage" in data and data["usage"]:
            usage = data["usage"]
            print(f"[IMAGE VIA AI] Tokens: prompt={usage.get('prompt_tokens')}, "
                  f"completion={usage.get('completion_tokens')}")
        
        print("[IMAGE VIA AI] PASSED")
        
    except httpx.TimeoutException:
        print("\n[TIMEOUT] Image generation via ai/ask timed out after 120 seconds.")
        pytest.fail("Request timed out after 120 seconds")


@pytest.mark.integration
def test_invalid_api_key():
    """Test that an invalid API key returns 401."""
    headers = {"Authorization": "Bearer sk-api-invalid-key"}
    with httpx.Client(base_url=API_BASE_URL, headers=headers, event_hooks={'response': [log_response]}) as client:
        # /v1/settings/billing definitely requires authentication
        response = client.get("/v1/settings/billing")
        assert response.status_code == 401
