"""Opaque artifact envelopes must be admitted before allocating complete objects."""

from io import BytesIO

import pytest

from backend.tests.s3_service_test_support import load_s3_service_module


class RecordingBody(BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def storage(body, length=None):
    module = load_s3_service_module()

    class Client:
        calls = 0

        def get_object(self, **kwargs):
            self.calls += 1
            return {'Body': body, **({'ContentLength': length} if length is not None else {})}

    service = module.S3UploadService(secrets_manager=None)
    service.client = Client()
    service.region_clients = {}
    service.environment = 'development'
    return service, module


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.anyio
@pytest.mark.parametrize('length', [None, 100])
async def test_oversized_object_is_rejected_and_closed_before_unbounded_read(length):
    body = RecordingBody(b'x' * 100)
    service, module = storage(body, length)
    with pytest.raises(module.HTTPException):
        await service.get_file('unknown-test-bucket', 'opaque', max_bytes=8)
    assert body.closed
    assert body.read_sizes == ([] if length is not None else [9])


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.anyio
async def test_exact_budget_object_is_read_without_truncation_and_closed():
    body = RecordingBody(b'cipher')
    service, _ = storage(body, 6)
    assert await service.get_file('unknown-test-bucket', 'opaque', max_bytes=6) == b'cipher'
    assert body.read_sizes == [7]
    assert body.closed


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_bounded_reader_checks_tombstone_before_object_access(monkeypatch):
    body = RecordingBody(b'cipher')
    service, module = storage(body, 6)

    async def tombstoned(*args):
        return True

    monkeypatch.setattr(module, '_storage_object_is_tombstoned', tombstoned)
    assert await service.get_file('unknown-test-bucket', 'opaque', max_bytes=6) is None
    assert service.client.calls == 0


# contract-test: supporting surface=rest_api assertions=storage.failover.health-reconciled
@pytest.mark.anyio
async def test_bounded_reader_preserves_regional_missing_object_failover():
    body = RecordingBody(b'cipher')
    service, module = storage(body, 6)
    secondary = service.client

    class MissingClient:
        def get_object(self, **kwargs):
            raise module.ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')

    service.client = MissingClient()
    service.region_name = 'nbg1'
    service.region_clients = {'nbg1': service.client, 'fsn1': secondary}
    assert await service.get_file('dev-openmates-chatfiles', 'opaque', max_bytes=6) == b'cipher'
    assert body.read_sizes == [7]
    assert body.closed
