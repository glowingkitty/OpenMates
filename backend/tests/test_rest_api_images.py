# backend/tests/test_rest_api_images.py
#
# Integration tests for the images app REST API endpoints.
#
# Architecture note — why image generation is NOT available via the public REST API:
#
#   Image generation (generate / generate_draft) uses a zero-knowledge hybrid
#   encryption model (see docs/architecture/security.md — "Server-Managed" tier):
#
#     1. The Celery task generates an AES key, encrypts the image bytes, and
#        uploads encrypted blobs to S3.
#     2. The embed content (incl. the plaintext AES key + S3 keys) is delivered
#        to the client as plaintext TOON over a WebSocket.
#     3. The browser client encrypts the embed content with the chat master key
#        and stores it in IndexedDB — the server never sees the plaintext key.
#     4. To download an image the client fetches the encrypted S3 blob and
#        decrypts it locally using the AES key from the embed.
#
#   A stateless REST API call has no WebSocket, no browser crypto, and no
#   master key — so it cannot complete step 3 or 4. Exposing a POST endpoint
#   would either require the server to store the AES key in plaintext (breaking
#   zero-knowledge) or return a result the caller can never decrypt.
#
#   Therefore the POST endpoints for generate / generate_draft are intentionally
#   omitted from the public REST API docs (api_config.expose_post: false in
#   app.yml). The GET metadata endpoints remain visible so developers know the
#   skill exists and can read the docs.
#
# TODO: Once the OpenMates CLI is implemented, add full integration tests here.
#   The CLI will authenticate (obtaining the master key), derive the embed key,
#   handle the WebSocket embed delivery, and encrypt/store the embed — exactly
#   as the web app does — enabling end-to-end testing of image generation.
#
# Current tests:
#   - GET  /v1/apps/images/skills/generate       → metadata visible (200)
#   - GET  /v1/apps/images/skills/generate_draft → metadata visible (200)
#   - POST /v1/apps/images/skills/generate       → 404 (endpoint not registered)
#   - POST /v1/apps/images/skills/generate_draft → 404 (endpoint not registered)
#
# Execution:
#   /home/superdev/projects/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_images.py

import pytest


# ─── GET metadata endpoints (should remain visible in REST API docs) ──────────

@pytest.mark.integration
def test_images_generate_skill_metadata_visible(api_client):
    """
    GET /v1/apps/images/skills/generate returns skill metadata.

    The GET endpoint must remain accessible so REST API developers can discover
    the skill, read its description, and understand it requires the web app or
    CLI for actual execution.
    """
    response = api_client.get("/v1/apps/images/skills/generate")
    assert response.status_code == 200, (
        f"Expected 200 for skill metadata, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data.get("id") == "generate", f"Unexpected skill id: {data.get('id')}"
    print(f"[OK] GET /v1/apps/images/skills/generate → 200, skill id={data.get('id')}")


@pytest.mark.integration
def test_images_generate_draft_skill_metadata_visible(api_client):
    """
    GET /v1/apps/images/skills/generate_draft returns skill metadata.

    Same rationale as test_images_generate_skill_metadata_visible — the metadata
    endpoint must be accessible even though POST is disabled.
    """
    response = api_client.get("/v1/apps/images/skills/generate_draft")
    assert response.status_code == 200, (
        f"Expected 200 for skill metadata, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data.get("id") == "generate_draft", f"Unexpected skill id: {data.get('id')}"
    print(f"[OK] GET /v1/apps/images/skills/generate_draft → 200, skill id={data.get('id')}")


# ─── POST endpoints must NOT be registered (zero-knowledge enforcement) ───────

@pytest.mark.integration
def test_images_generate_post_not_supported(api_client):
    """
    POST /v1/apps/images/skills/generate is not available via the public REST API.

    Image generation requires a WebSocket connection and client-side encryption
    (browser crypto / CLI). The POST endpoint is intentionally omitted from the
    API (api_config.expose_post: false) to prevent confusion and protect the
    zero-knowledge architecture.

    Expected: 405 Method Not Allowed — the GET route exists (metadata) but POST is not registered.

    TODO: Once the CLI is implemented, replace this test with a full end-to-end
    test that authenticates, derives the master key, dispatches the Celery task,
    handles the WebSocket embed delivery, encrypts the embed, and downloads the
    generated image via the embed file endpoint.
    """
    payload = {"requests": [{"prompt": "a cute cat"}]}
    response = api_client.post(
        "/v1/apps/images/skills/generate",
        json=payload,
    )
    # 405 Method Not Allowed because GET is registered for the path but POST is not.
    # (404 would appear only if no method at all were registered for the path.)
    assert response.status_code == 405, (
        f"Expected 405 (POST not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] POST /v1/apps/images/skills/generate → 405 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )


@pytest.mark.integration
def test_images_generate_draft_post_not_supported(api_client):
    """
    POST /v1/apps/images/skills/generate_draft is not available via the public REST API.

    Same rationale as test_images_generate_post_not_supported.

    TODO: Once the CLI is implemented, replace this test with a full end-to-end
    test covering the draft (FLUX-Schnell) generation path.
    """
    payload = {"requests": [{"prompt": "a quick draft cat"}]}
    response = api_client.post(
        "/v1/apps/images/skills/generate_draft",
        json=payload,
    )
    # 405 Method Not Allowed because GET is registered for the path but POST is not.
    assert response.status_code == 405, (
        f"Expected 405 (POST not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] POST /v1/apps/images/skills/generate_draft → 405 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )
