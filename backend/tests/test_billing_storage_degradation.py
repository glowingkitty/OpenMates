"""
Billing invoice storage degradation contract tests.

These focused tests keep Hetzner transport failures distinguishable from
OpenMates configuration failures. They intentionally avoid importing Celery so
the storage boundary can be verified in a dependency-light test environment.
"""

from botocore.exceptions import ClientError, EndpointConnectionError

from backend.core.api.app.services.s3 import service as s3_service


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_hetzner_upload_failure_classification() -> None:
    degraded = s3_service.classify_hetzner_upload_error(
        EndpointConnectionError(endpoint_url="https://nbg1.your-objectstorage.com")
    )
    configuration = s3_service.classify_hetzner_upload_error(
        ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "denied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
    )

    assert degraded.provider == "Hetzner Object Storage"
    assert degraded.classification == "external_provider_degraded"
    assert degraded.retryable is True
    assert configuration.provider == "Hetzner Object Storage"
    assert configuration.classification == "internal_storage_configuration"
    assert configuration.retryable is False


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_hetzner_client_error_classification_matrix() -> None:
    cases = [
        ("SlowDown", 429, "external_provider_degraded", True),
        ("InternalError", 500, "external_provider_degraded", True),
        ("NoSuchBucket", 404, "internal_storage_configuration", False),
        ("InvalidRequest", 400, "internal_storage_configuration", False),
    ]

    for error_code, status_code, classification, retryable in cases:
        error = ClientError(
            {
                "Error": {"Code": error_code, "Message": "provider detail"},
                "ResponseMetadata": {"HTTPStatusCode": status_code},
            },
            "PutObject",
        )

        classified = s3_service.classify_hetzner_upload_error(error)

        assert classified.classification == classification
        assert classified.retryable is retryable
        assert "provider detail" not in str(classified)
