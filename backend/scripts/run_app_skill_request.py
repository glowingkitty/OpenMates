#!/usr/bin/env python3
# backend/scripts/run_app_skill_request.py
#
# Trigger app skill execution directly from the API container and create embeds
# without going through the full websocket + UI flow.
#
# WHY THIS EXISTS:
# - Lets us reproduce app_skill_use embed behavior with real data (no mocks).
# - Avoids UI complexity: no browser, no streaming UI required.
# - Produces embed references you can paste into a message to render embeds.
#
# HOW IT WORKS (high-level):
# 1. Calls the app service (e.g., app-web) skill endpoint directly via HTTP.
# 2. Uses EmbedService to create parent/child embeds from the real results.
# 3. Prints embed references and metadata for debugging.
#
# NOTE:
# - This does NOT update chat message content in Directus (messages are client-encrypted).
# - To render embeds in the UI, paste the printed embed reference JSON into a message.
# - Embeds are cached server-side and sent via send_embed_data events if a client is connected.

import argparse
import asyncio
import hashlib
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.embed_service import EmbedService

logger = logging.getLogger(__name__)


APP_HOSTNAMES = {
    "ai": "app-ai",
    "web": "app-web",
    "videos": "app-videos",
    "news": "app-news",
    "maps": "app-maps",
    "code": "app-code",
}


def _hash_id(value: str) -> str:
    """Hash an ID for cache/Directus metadata consistency."""
    return hashlib.sha256(value.encode()).hexdigest()


async def _get_user_vault_key_id(
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
) -> str:
    """
    Retrieve the user's vault_key_id required for embed encryption.
    Tries cache first, then Directus user profile.
    """
    cached = await cache_service.get_user_vault_key_id(user_id)
    if cached:
        return cached

    success, profile, message = await directus_service.user.get_user_profile(user_id)
    if not success or not profile:
        raise RuntimeError(f"Failed to load user profile: {message}")

    vault_key_id = profile.get("vault_key_id")
    if not vault_key_id:
        raise RuntimeError("User profile missing vault_key_id")

    return vault_key_id


async def _call_app_skill(
    app_id: str,
    skill_id: str,
    input_data: Dict[str, Any],
    parameters: Dict[str, Any],
    user_id: str,
    api_key_name: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """
    Call the app service skill endpoint directly using real services.
    Mirrors the internal call pattern used by the external API.
    """
    hostname = APP_HOSTNAMES.get(app_id)
    if not hostname:
        raise RuntimeError(f"Unknown app_id: {app_id}")

    url = f"http://{hostname}:8000/skills/{skill_id}"
    headers = {
        "Content-Type": "application/json",
        "X-External-User-ID": user_id,
        "X-External-User-Email": "",
        "X-API-Key-Name": api_key_name,
    }
    payload = {
        "input_data": input_data,
        "parameters": parameters,
        "context": {
            "user_id": user_id,
            "api_key_name": api_key_name,
            "external_request": True,
        },
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Skill call failed ({response.status_code}): {response.text}")
        return response.json()


def _extract_skill_payload(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize skill response payload across possible formats:
    - Direct app service response (e.g., {"results": [...], "provider": "Brave Search"})
    - Wrapped response (e.g., {"success": true, "data": {...}})
    """
    if "success" in response_json and "data" in response_json:
        return response_json["data"] or {}
    return response_json


def _build_requests_from_queries(queries: List[str]) -> List[Dict[str, Any]]:
    """
    Build the requests list for search-style skills.
    Uses 1-indexed IDs to match the backend placeholder creation logic.
    """
    requests: List[Dict[str, Any]] = []
    for idx, query in enumerate(queries, start=1):
        requests.append({"id": idx, "query": query})
    return requests


def _group_results_for_requests(
    payload: Dict[str, Any],
    input_requests: List[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """
    Convert grouped search results into a list of (request_metadata, results) tuples.
    """
    provider = payload.get("provider")
    request_map = {str(req.get("id")): req for req in input_requests}
    grouped_results = payload.get("results") or []

    result_groups: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for entry in grouped_results:
        request_id = str(entry.get("id"))
        request_metadata = dict(request_map.get(request_id, {}))
        if provider and "provider" not in request_metadata:
            request_metadata["provider"] = provider
        results = entry.get("results") or []
        result_groups.append((request_metadata, results))

    return result_groups


async def _create_embeds_from_results(
    embed_service: EmbedService,
    app_id: str,
    skill_id: str,
    results: List[Dict[str, Any]],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_vault_key_id: str,
    request_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Use EmbedService to create app_skill_use embeds (parent + children if composite).
    """
    user_id_hash = _hash_id(user_id)
    return await embed_service.create_embeds_from_skill_results(
        app_id=app_id,
        skill_id=skill_id,
        results=results,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        user_vault_key_id=user_vault_key_id,
        task_id=None,
        log_prefix="[run_app_skill_request]",
        request_metadata=request_metadata,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trigger app skill use via internal API and create embeds."
    )
    parser.add_argument("--app-id", required=True, help="App ID (e.g., web, news, videos)")
    parser.add_argument("--skill-id", required=True, help="Skill ID (e.g., search, read)")
    parser.add_argument("--user-id", required=True, help="User ID (UUID)")
    parser.add_argument("--chat-id", default=str(uuid.uuid4()), help="Chat ID (UUID)")
    parser.add_argument("--message-id", default=str(uuid.uuid4()), help="Message ID (UUID)")
    parser.add_argument("--query", action="append", help="Search query (repeatable)")
    parser.add_argument("--input-json", help="Raw input_data JSON for non-search skills")
    parser.add_argument("--parameters-json", default="{}", help="Raw parameters JSON (default: {})")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds (default: 60)")
    parser.add_argument("--api-key-name", default="script", help="API key name label")
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Only call the skill and print response (skip embed creation).",
    )
    args = parser.parse_args()

    if args.query and args.input_json:
        raise ValueError("Use --query OR --input-json, not both.")

    # Build input_data
    if args.query:
        input_requests = _build_requests_from_queries(args.query)
        input_data = {"requests": input_requests}
    elif args.input_json:
        input_data = json.loads(args.input_json)
        input_requests = input_data.get("requests", [])
    else:
        raise ValueError("Provide at least one --query or --input-json.")

    parameters = json.loads(args.parameters_json) if args.parameters_json else {}

    logger.info("Starting app skill execution")
    logger.info("app_id=%s skill_id=%s chat_id=%s message_id=%s", args.app_id, args.skill_id, args.chat_id, args.message_id)

    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )
    embed_service = EmbedService(
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )

    try:
        user_vault_key_id = await _get_user_vault_key_id(cache_service, directus_service, args.user_id)
        response_json = await _call_app_skill(
            app_id=args.app_id,
            skill_id=args.skill_id,
            input_data=input_data,
            parameters=parameters,
            user_id=args.user_id,
            api_key_name=args.api_key_name,
            timeout_seconds=args.timeout,
        )

        payload = _extract_skill_payload(response_json)
        print("\n=== Raw Skill Response ===")
        print(json.dumps(payload, indent=2, default=str))

        if args.raw_only:
            return

        # Create embeds from results
        if isinstance(payload.get("results"), list) and payload.get("results"):
            # Grouped results (search skill) format: [{"id": X, "results": [...]}]
            grouped = _group_results_for_requests(payload, input_requests)
            print("\n=== Embed References ===")
            for idx, (request_metadata, results) in enumerate(grouped, start=1):
                embed_info = await _create_embeds_from_results(
                    embed_service=embed_service,
                    app_id=args.app_id,
                    skill_id=args.skill_id,
                    results=results,
                    chat_id=args.chat_id,
                    message_id=args.message_id,
                    user_id=args.user_id,
                    user_vault_key_id=user_vault_key_id,
                    request_metadata=request_metadata,
                )
                if embed_info and embed_info.get("embed_reference"):
                    print(f"\n# Request {idx} (query={request_metadata.get('query', 'N/A')})")
                    print(embed_info["embed_reference"])
        else:
            # Non-search skill format: treat payload as a single results list
            results = payload.get("results") or []
            embed_info = await _create_embeds_from_results(
                embed_service=embed_service,
                app_id=args.app_id,
                skill_id=args.skill_id,
                results=results,
                chat_id=args.chat_id,
                message_id=args.message_id,
                user_id=args.user_id,
                user_vault_key_id=user_vault_key_id,
                request_metadata=input_data,
            )
            print("\n=== Embed Reference ===")
            if embed_info and embed_info.get("embed_reference"):
                print(embed_info["embed_reference"])
            else:
                print("No embed reference returned.")

        print("\n=== Notes ===")
        print("Embeds were created and cached on the server.")
        print("Paste the embed reference JSON into a chat message to render in UI.")

    finally:
        await directus_service.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(main())
