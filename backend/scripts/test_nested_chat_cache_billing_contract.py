#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Isolated product-stack proof: main billing persists parent/child/grandchild cache receipts.

No AI/provider requests are made. Synthetic provider counters enter the real
normal billing consumer, internal authenticated API, encrypted ledger and usage.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main(email: str) -> dict:
    if (
        os.getenv("SERVER_ENVIRONMENT") != "development"
        or os.getenv("PRODUCTION_URL") != "http://localhost:5173"
    ):
        raise RuntimeError("Disposable isolated API required")
    allowed = {
        value
        for key, value in os.environ.items()
        if key.startswith("OPENMATES_TEST_ACCOUNT_CI_") and key.endswith("_EMAIL")
    }
    if email not in allowed or not os.getenv("INTERNAL_API_SHARED_TOKEN"):
        raise RuntimeError(
            "Fresh allowlisted CI owner and internal credential required"
        )
    from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
    from backend.apps.ai.processing.main_processor import _customer_cache_pricing_scope
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks.stream_consumer import _handle_normal_billing
    from backend.apps.ai.utils.llm_utils import _snapshot_for_customer_scope
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.sub_chat_orchestration_service import (
        SubChatOrchestrationService,
    )
    from backend.core.api.app.utils.config_manager import config_manager
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.shared.python_schemas.llm_usage import normalize_provider_usage

    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    charge_ids: list[str] = []
    refunds: list[dict] = []
    headers = {"X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"]}
    async with httpx.AsyncClient(
        base_url="http://api:8000", headers=headers, timeout=45, trust_env=False
    ) as client:
        try:
            email_hash = base64.b64encode(
                hashlib.sha256(email.strip().lower().encode()).digest()
            ).decode()
            users = await directus.get_items(
                "directus_users",
                params={
                    "filter[hashed_email][_eq]": email_hash,
                    "fields": "id,vault_key_id",
                    "limit": 2,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            assert len(users) == 1 and users[0]["vault_key_id"]
            owner = users[0]
            owner_hash = hashlib.sha256(owner["id"].encode()).hexdigest()

            async def balance():
                rows = await directus.get_items(
                    "directus_users",
                    params={
                        "filter[id][_eq]": owner["id"],
                        "fields": "encrypted_credit_balance",
                        "limit": 1,
                    },
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                return int(
                    await encryption.decrypt_with_user_key(
                        rows[0]["encrypted_credit_balance"], owner["vault_key_id"]
                    )
                )

            initial = await balance()
            assert initial >= 60
            root, child, grandchild = [str(uuid.uuid4()) for _ in range(3)]
            orchestration_id, root_turn_id = str(uuid.uuid4()), str(uuid.uuid4())
            orchestration = SubChatOrchestrationService(directus)
            authority = {
                "protocol_version": 1,
                "orchestration_id": orchestration_id,
                "hashed_user_id": owner_hash,
            }
            await directus.create_item(
                "chats",
                {"id": root, "hashed_user_id": owner_hash, "encrypted_title": ""},
                admin_required=True,
            )
            await orchestration.execute(
                "create_root",
                {
                    **authority,
                    "root_chat_id": root,
                    "root_turn_id": root_turn_id,
                    "descendant_limit": 2,
                    "credit_limit": 60,
                },
            )
            task_ids = [str(uuid.uuid4()) for _ in range(3)]
            for depth, (parent_id, child_id) in enumerate(
                [(root, child), (child, grandchild)]
            ):
                dispatch_token = str(uuid.uuid4())
                await orchestration.execute(
                    "prepare_batch",
                    {
                        **authority,
                        "batch_id": str(uuid.uuid4()),
                        "parent_chat_id": parent_id,
                        "parent_depth": depth,
                        "is_continuation": False,
                        "children": [
                            {
                                "child_chat_id": child_id,
                                "user_message_id": str(uuid.uuid4()),
                                "dispatch_token": dispatch_token,
                                "budget_limit": 30,
                            }
                        ],
                    },
                )
                await orchestration.execute(
                    "claim_child",
                    {
                        **authority,
                        "child_chat_id": child_id,
                        "dispatch_token": dispatch_token,
                        "inference_task_id": task_ids[depth + 1],
                        "is_continuation": False,
                    },
                )
            model_id = "deepseek/deepseek-v4.1-flash"
            raw = OpenAIUsageMetadata(
                input_tokens=11000,
                output_tokens=275,
                total_tokens=11275,
                cache_read_input_tokens=8000,
                inference_host="baseten",
            )
            prepaid_total = 0
            for depth, chat_id in enumerate([root, child, grandchild]):
                task_id = task_ids[depth]
                operation_id = f"ai-ask:{task_id}:main"
                charge_ids.append(operation_id)
                request = AskSkillRequest(
                    chat_id=chat_id,
                    message_id=str(uuid.uuid4()),
                    user_id=owner["id"],
                    user_id_hash=owner_hash,
                    message_history=[],
                    root_chat_id=root,
                    root_turn_id=root_turn_id,
                    orchestration_id=orchestration_id,
                    is_sub_chat=depth > 0,
                    sub_chat_depth=depth,
                    parent_id=[None, root, child][depth],
                )
                assert _customer_cache_pricing_scope(request)
                tariff = _snapshot_for_customer_scope(
                    config_manager.get_model_pricing("deepseek", "deepseek-v4.1-flash"),
                    cache_pricing_enabled=_customer_cache_pricing_scope(request),
                )
                usage = normalize_provider_usage(
                    raw,
                    model_id=model_id,
                    provider_kind="openai",
                    inference_host="baseten",
                    tariff_snapshot=tariff,
                    attempt_id=task_id,
                )
                await orchestration.execute(
                    "reserve_operation",
                    {
                        **authority,
                        "operation_id": operation_id + ":iteration:0",
                        "charge_id": operation_id,
                        "root_chat_id": root,
                        "actual_chat_id": chat_id,
                        "depth": depth,
                        "app_id": "ai",
                        "skill_id": "ask",
                        "phase": "inference_0",
                        "quoted_credits": 20,
                    },
                )
                reserve = await client.post(
                    "/internal/billing/reserve",
                    json={
                        "user_id": owner["id"],
                        "user_id_hash": owner_hash,
                        "idempotency_key": operation_id,
                        "quoted_credits": 20,
                        "app_id": "ai",
                        "skill_id": "ask",
                    },
                )
                reserve.raise_for_status()
                kwargs = dict(
                    usage=raw,
                    preprocessing_result=SimpleNamespace(
                        selected_main_llm_model_id=model_id,
                        server_provider_name="baseten",
                        server_region="global",
                    ),
                    request_data=request,
                    task_id=task_id,
                    log_prefix="[isolated-nested-cache]",
                    successful_model_id=model_id,
                    usage_by_model=[usage.to_bucket()],
                    billing_reservation_required=True,
                )
                result = await _handle_normal_billing(**kwargs)
                receipt = result["llm_usage_breakdown"]
                assert result["total_credits"] == receipt["credits_charged"] == 3
                assert receipt["cache_read_input_tokens"] == 8000
                assert receipt["entries"][0]["billing_mode"] == "cache_aware"
                prepaid_total += 3
                assert await balance() == initial - prepaid_total
                replay = await _handle_normal_billing(**kwargs)
                assert (
                    replay["total_credits"] == 3
                    and await balance() == initial - prepaid_total
                )
                rows = await directus.get_items(
                    "usage",
                    params={
                        "filter[charge_id][_eq]": operation_id,
                        "fields": "id,root_chat_id,actual_chat_id,depth,encrypted_llm_usage_breakdown",
                        "limit": 2,
                    },
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                assert len(rows) == 1
                saved = rows[0]
                assert (
                    saved["root_chat_id"] == root
                    and saved["actual_chat_id"] == chat_id
                    and saved["depth"] == depth
                )
                saved_receipt = json.loads(
                    await encryption.decrypt_with_user_key(
                        saved["encrypted_llm_usage_breakdown"], owner["vault_key_id"]
                    )
                )
                assert (
                    saved_receipt["credits_charged"] == 3
                    and saved_receipt["cache_read_input_tokens"] == 8000
                )
                refunds.append(
                    {
                        "user_id": owner["id"],
                        "user_id_hash": owner_hash,
                        "credits": 3,
                        "app_id": "system",
                        "skill_id": "nested_cache_billing_contract",
                        "idempotency_key": operation_id + ":refund",
                        "reason": "Disposable nested cache proof cleanup",
                    }
                )
            assert prepaid_total == 9
            root_state = await orchestration.execute("get_root_state", authority)
            assert (
                root_state["spent_credits"] == 9 and root_state["reserved_credits"] == 0
            )
            assert root_state["descendant_count"] == 2
            for payload in refunds:
                response = await client.post("/internal/billing/refund", json=payload)
                response.raise_for_status()
            assert await balance() == initial
            return {
                "passed": True,
                "root_chat_id": root,
                "depths": [0, 1, 2],
                "year_month": datetime.now(timezone.utc).strftime("%Y-%m"),
                "total_credits": 9,
                "root_spent_credits": root_state["spent_credits"],
                "root_reserved_credits": root_state["reserved_credits"],
                "charges": 3,
                "replay_debits": 0,
                "balance_restored": True,
            }
        finally:
            await directus.close()
            await cache.close()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    with redirect_stdout(sys.stderr):
        result = asyncio.run(main(json.load(sys.stdin)["email"]))
    print(json.dumps(result))
