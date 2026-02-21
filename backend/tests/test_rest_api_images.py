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
#   master key — so it cannot complete step 3 or 4. Exposing endpoints would
#   either require the server to store the AES key in plaintext (breaking
#   zero-knowledge) or return a result the caller can never decrypt.
#
#   Therefore BOTH the GET metadata and POST execution endpoints for
#   generate / generate_draft are intentionally omitted from the public REST
#   API docs (api_config.expose_get: false, api_config.expose_post: false in
#   app.yml). The skills are completely hidden from /docs.
#
# TODO: Once the OpenMates CLI is implemented, add full integration tests here.
#   The CLI will authenticate (obtaining the master key), derive the embed key,
#   handle the WebSocket embed delivery, and encrypt/store the embed — exactly
#   as the web app does — enabling end-to-end testing of image generation.
#
# Current tests:
#   - GET  /v1/apps/images/skills/generate       → 404 (endpoint not registered)
#   - GET  /v1/apps/images/skills/generate_draft → 404 (endpoint not registered)
#   - POST /v1/apps/images/skills/generate       → 404 (endpoint not registered)
#   - POST /v1/apps/images/skills/generate_draft → 404 (endpoint not registered)
#
# Execution:
#   /home/superdev/projects/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_images.py

import pytest


# ─── GET metadata endpoints must NOT be registered (fully hidden from REST API docs) ─

@pytest.mark.integration
def test_images_generate_skill_metadata_hidden(api_client):
    """
    GET /v1/apps/images/skills/generate is not registered in the public REST API.

    Both the GET metadata and POST execution endpoints are hidden (api_config:
    expose_get: false, expose_post: false) to prevent the skill from appearing in
    /docs at all. Image generation requires a WebSocket connection and client-side
    encryption — it cannot be used from a stateless REST client without breaking
    the zero-knowledge architecture.

    Expected: 404 Not Found — no route is registered for this path.
    """
    response = api_client.get("/v1/apps/images/skills/generate")
    assert response.status_code == 404, (
        f"Expected 404 (GET not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] GET /v1/apps/images/skills/generate → 404 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )


@pytest.mark.integration
def test_images_generate_draft_skill_metadata_hidden(api_client):
    """
    GET /v1/apps/images/skills/generate_draft is not registered in the public REST API.

    Same rationale as test_images_generate_skill_metadata_hidden.

    Expected: 404 Not Found — no route is registered for this path.
    """
    response = api_client.get("/v1/apps/images/skills/generate_draft")
    assert response.status_code == 404, (
        f"Expected 404 (GET not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] GET /v1/apps/images/skills/generate_draft → 404 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )


# ─── POST endpoints must NOT be registered (zero-knowledge enforcement) ───────

@pytest.mark.integration
def test_images_generate_post_not_supported(api_client):
    """
    POST /v1/apps/images/skills/generate is not available via the public REST API.

    Image generation requires a WebSocket connection and client-side encryption
    (browser crypto / CLI). Both GET and POST endpoints are intentionally omitted
    from the API (api_config.expose_get: false, api_config.expose_post: false) to
    keep the skill completely hidden from /docs and prevent confusion.

    Expected: 404 Not Found — no route is registered for this path at all.

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
    # 404 Not Found because neither GET nor POST is registered for this path.
    assert response.status_code == 404, (
        f"Expected 404 (POST not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] POST /v1/apps/images/skills/generate → 404 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )


@pytest.mark.integration
def test_images_generate_draft_post_not_supported(api_client):
    """
    POST /v1/apps/images/skills/generate_draft is not available via the public REST API.

    Same rationale as test_images_generate_post_not_supported.

    Expected: 404 Not Found — no route is registered for this path at all.

    TODO: Once the CLI is implemented, replace this test with a full end-to-end
    test covering the draft (FLUX-Schnell) generation path.
    """
    payload = {"requests": [{"prompt": "a quick draft cat"}]}
    response = api_client.post(
        "/v1/apps/images/skills/generate_draft",
        json=payload,
    )
    # 404 Not Found because neither GET nor POST is registered for this path.
    assert response.status_code == 404, (
        f"Expected 404 (POST not registered), got {response.status_code}: {response.text}"
    )
    print(
        "[OK] POST /v1/apps/images/skills/generate_draft → 404 "
        "(endpoint intentionally not registered — use web app or CLI)"
    )
