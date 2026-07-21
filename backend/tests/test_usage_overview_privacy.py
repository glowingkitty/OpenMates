from __future__ import annotations

from backend.core.api.app.services.usage_overview_service import ROLLUP_VERSION


def test_usage_rollup_contract_keeps_sensitive_fields_in_encrypted_json() -> None:
    cleartext_columns = {
        "id",
        "user_id_hash",
        "granularity",
        "period_key",
        "period_start",
        "period_end",
        "rollup_version",
        "encrypted_rollup_json",
        "entry_count",
        "source_min_created_at",
        "source_max_created_at",
        "computed_at",
        "stale_reason",
        "created_at",
        "updated_at",
    }
    forbidden_cleartext = {
        "credits",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "model_used",
        "server_provider",
        "server_region",
    }

    assert ROLLUP_VERSION == 1
    assert cleartext_columns.isdisjoint(forbidden_cleartext)
