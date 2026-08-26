# Compliance-bucket lifecycle contract tests.
# Financial and audit objects share one physical bucket but not one retention.
# Rule generation must be deterministic and preserve both prefix policies.
# These tests use a fake S3 client and perform no network operations.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

from typing import Any

from backend.tests.s3_service_test_support import ensure_s3_dependencies

ensure_s3_dependencies()
from backend.core.api.app.services.s3 import lifecycle  # noqa: E402


class RecordingS3Client:
    def __init__(self, existing_rules: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.existing_rules = existing_rules or []

    def get_bucket_lifecycle_configuration(self, **kwargs: Any) -> dict[str, Any]:
        return {"Rules": self.existing_rules}

    def put_bucket_lifecycle_configuration(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


COMPLIANCE_BUCKET_CONFIGS = {
    "financial_compliance_logs": {
        "name": "openmates-compliance-logs-backups",
        "dev_name": "dev-openmates-compliance-logs-backups",
        "lifecycle_policy": 3650,
        "lifecycle_prefix": "financial-compliance/",
    },
    "audit_compliance_logs": {
        "name": "openmates-compliance-logs-backups",
        "dev_name": "dev-openmates-compliance-logs-backups",
        "lifecycle_policy": 730,
        "lifecycle_prefix": "audit-compliance/",
    },
}


# contract-test: direct surface=rest_api assertions=storage.retention.system-generation-only
def test_shared_compliance_bucket_receives_both_prefix_rules_in_one_update() -> None:
    client = RecordingS3Client()

    lifecycle.apply_lifecycle_policies(client, COMPLIANCE_BUCKET_CONFIGS, environment="development")

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == "dev-openmates-compliance-logs-backups"
    assert call["LifecycleConfiguration"]["Rules"] == [
        {
            "ID": "OpenMates-ExpireAuditComplianceAfter730Days",
            "Status": "Enabled",
            "Filter": {"Prefix": "audit-compliance/"},
            "Expiration": {"Days": 730},
        },
        {
            "ID": "OpenMates-ExpireFinancialComplianceAfter3650Days",
            "Status": "Enabled",
            "Filter": {"Prefix": "financial-compliance/"},
            "Expiration": {"Days": 3650},
        },
    ]


# contract-test: supporting surface=rest_api assertions=storage.retention.system-generation-only
def test_lifecycle_rule_generation_is_identical_for_each_region() -> None:
    rules = lifecycle.build_lifecycle_rules(COMPLIANCE_BUCKET_CONFIGS)

    assert rules == lifecycle.build_lifecycle_rules(COMPLIANCE_BUCKET_CONFIGS)
    assert all(rule["Filter"]["Prefix"] for rule in rules)


# contract-test: direct surface=rest_api assertions=storage.retention.system-generation-only
def test_lifecycle_reconciliation_preserves_unmanaged_rules() -> None:
    unmanaged_rule = {
        "ID": "Operator-AbortIncompleteMultipartUploads",
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
    }
    stale_managed_rule = {
        "ID": "OpenMates-ExpireAuditComplianceAfter365Days",
        "Status": "Enabled",
        "Filter": {"Prefix": "audit-compliance/"},
        "Expiration": {"Days": 365},
    }
    legacy_whole_bucket_rule = {
        "ID": "ExpireAfter730Days",
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "Expiration": {"Days": 730},
    }
    client = RecordingS3Client(
        existing_rules=[unmanaged_rule, stale_managed_rule, legacy_whole_bucket_rule]
    )

    lifecycle.apply_lifecycle_policies(client, COMPLIANCE_BUCKET_CONFIGS, environment="development")

    rules = client.calls[0]["LifecycleConfiguration"]["Rules"]
    assert rules[0] == unmanaged_rule
    assert stale_managed_rule not in rules
    assert legacy_whole_bucket_rule not in rules
    assert len(rules) == 3
