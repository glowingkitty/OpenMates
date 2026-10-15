# contract-test-file: tooling
"""Publication cannot grant access or touch data outside the exact target."""

from copy import deepcopy
from contextlib import closing
import hashlib
import io
import json
from types import SimpleNamespace

import boto3
from botocore.exceptions import ClientError
import httpx
from PIL import Image
import pytest

from backend.scripts import publish_newsletter_s3_assets as publisher
from backend.scripts.publish_newsletter_s3_assets import (
    PRIVATE_PROBE_KEY, STATIC_DIR, atomic_json, publish_to_s3, validated_local_assets, validate_policy, validate_image_bytes,
    newsletter_s3_client_config,
)
from backend.shared.python_utils.newsletter_assets import (
    ASSET_MAP_PATH, NEWSLETTER_S3_BUCKETS, NEWSLETTER_S3_PREFIX, newsletter_public_policy, newsletter_image_url,
    newsletter_s3_endpoint,
)
from scripts.publish_newsletter_assets import publish_sources


def _error(code, status):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "ScopedOperation")


def test_s3_put_serializes_signed_payload_without_optional_streaming_checksum():
    data = b"newsletter image serialization probe"
    captured = {}

    class RequestCaptured(Exception):
        pass

    def capture(request, **kwargs):
        captured["headers"] = {key.lower(): value for key, value in request.headers.items()}
        captured["body"] = request.body.read() if hasattr(request.body, "read") else request.body
        captured["url"] = request.url
        raise RequestCaptured

    config = newsletter_s3_client_config()
    assert config.connect_timeout == 10 and config.read_timeout == 20
    assert config.retries == {"max_attempts": 0}
    with closing(boto3.client("s3", endpoint_url="https://nbg1.your-objectstorage.com", region_name="nbg1",
                              aws_access_key_id="test-access", aws_secret_access_key="test-secret", config=config)) as client:
        client.meta.events.register("before-send.s3.PutObject", capture)
        with pytest.raises(RequestCaptured):
            client.put_object(Bucket=NEWSLETTER_S3_BUCKETS["development"],
                              Key=NEWSLETTER_S3_PREFIX + "test.jpg", Body=data,
                              ContentType="image/jpeg", ACL="private", IfNoneMatch="*")
    headers = captured["headers"]
    assert headers["x-amz-content-sha256"] == hashlib.sha256(data).hexdigest().encode()
    assert headers["if-none-match"] == b"*"
    assert "x-amz-trailer" not in headers and "x-amz-sdk-checksum-algorithm" not in headers
    assert b"aws-chunked" not in headers.get("content-encoding", b"")
    assert captured["body"] == data
    assert captured["url"].startswith("https://nbg1.your-objectstorage.com/" + NEWSLETTER_S3_BUCKETS["development"] + "/")


class Store:
    def __init__(self, *, exists=False, environment="development"):
        self.bucket = NEWSLETTER_S3_BUCKETS[environment]
        self.meta = SimpleNamespace(endpoint_url="https://nbg1.your-objectstorage.com", region_name="nbg1")
        self.exists = exists
        self.policy = newsletter_public_policy(self.bucket) if exists else None
        self.objects = {}
        self.calls = []
        self.acl = {"Owner": {"ID": "newsletter-owner"}, "Grants": [{
            "Permission": "FULL_CONTROL", "Grantee": {"Type": "CanonicalUser", "ID": "newsletter-owner"},
        }]}

    def call(self, name, arguments):
        assert arguments["Bucket"] == self.bucket
        self.calls.append((name, deepcopy(arguments)))

    def head_bucket(self, **kwargs):
        self.call("head_bucket", kwargs)
        if not self.exists:
            raise _error("404", 404)

    def create_bucket(self, **kwargs):
        self.call("create_bucket", kwargs)
        assert not self.exists and kwargs["ACL"] == "private"
        self.exists = True

    def get_bucket_policy(self, **kwargs):
        self.call("get_bucket_policy", kwargs)
        if not self.exists:
            raise _error("NoSuchBucket", 404)
        if self.policy is None:
            raise _error("NoSuchBucketPolicy", 404)
        return {"Policy": json.dumps(self.policy)}

    def put_bucket_policy(self, **kwargs):
        self.call("put_bucket_policy", kwargs)
        assert self.policy is None and not self.objects
        self.policy = json.loads(kwargs["Policy"])
        validate_policy(self.policy, self.bucket)

    def get_bucket_acl(self, **kwargs):
        self.call("get_bucket_acl", kwargs)
        return deepcopy(self.acl)

    def get_object_acl(self, **kwargs):
        self.call("get_object_acl", kwargs)
        return deepcopy(self.acl)

    def list_objects_v2(self, **kwargs):
        self.call("list_objects_v2", kwargs)
        return {"Contents": [{"Key": key, "Size": len(value["data"])} for key, value in self.objects.items()], "IsTruncated": False}

    def put_object(self, **kwargs):
        self.call("put_object", kwargs)
        assert kwargs["IfNoneMatch"] == "*" and kwargs["ACL"] == "private"
        key = kwargs["Key"]
        assert key.startswith(NEWSLETTER_S3_PREFIX) or key == PRIVATE_PROBE_KEY
        if key in self.objects:
            raise _error("PreconditionFailed", 412)
        self.objects[key] = {"data": kwargs["Body"], "content_type": kwargs["ContentType"], "sha256": kwargs["Metadata"]["sha256"]}

    def head_object(self, **kwargs):
        self.call("head_object", kwargs)
        image = self.objects[kwargs["Key"]]
        return {"ContentLength": len(image["data"]), "ContentType": image["content_type"], "Metadata": {"sha256": image["sha256"]}}

    def get_object(self, **kwargs):
        self.call("get_object", kwargs)
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]]["data"])}

    def public(self, *, unsafe=None):
        def response(request):
            assert request.headers.get("authorization") is None
            assert request.url.host == self.bucket + ".nbg1.your-objectstorage.com"
            key = request.url.path.lstrip("/")
            if request.method == "PUT":
                return httpx.Response(200 if unsafe == "write" else 403)
            if request.url.query:
                return httpx.Response(200 if unsafe == "list" else 403)
            if key == PRIVATE_PROBE_KEY:
                return httpx.Response(200 if unsafe == "private-prefix" else 403)
            image = self.objects[key]
            return httpx.Response(404 if unsafe == "image" else 200, content=image["data"], headers={"Content-Type": image["content_type"]})
        return httpx.Client(transport=httpx.MockTransport(response), follow_redirects=False)


@pytest.fixture
def assets(tmp_path, monkeypatch):
    for name in ("S3_ENDPOINT_URL", "NEWSLETTER_CI_ASSET_MAP_PATH"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "campaign").mkdir()
    Image.new("RGB", (64, 32), "red").save(tmp_path / "campaign/header.png")
    publish_sources(["campaign/header.png"], repo_root=tmp_path)
    payload, objects = validated_local_assets(tmp_path)
    return tmp_path, payload, objects


def test_first_publication_is_narrow_immutable_verified_and_idempotent(assets):
    root, payload, objects = assets
    store = Store()
    with store.public() as public:
        receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert receipt["status"] == "verified" and receipt["created_bucket"]
    assert ready["delivery_transport"] == "s3" and payload.get("s3_publications") is None
    assert ready["s3_publications"]["development"]["verified_filenames"] == sorted(objects)
    atomic_json(root / ASSET_MAP_PATH, ready)
    url = newsletter_image_url("campaign/header.png", "https://app.dev.openmates.org", repo_root=root)
    assert url.startswith("https://dev-openmates-newsletter-assets.nbg1.your-objectstorage.com/newsletter-images/")
    with pytest.raises(ValueError, match="unpublished or stale"):
        newsletter_image_url("campaign/header.png", "https://openmates.org", repo_root=root)
    store.calls.clear()
    with store.public() as public:
        receipt, _ = publish_to_s3(ready, objects, environment="development", client=store, public=public, apply=True)
    assert receipt["uploaded"] == 0 and receipt["existing"] == len(objects)
    assert not any(name.startswith(("put_", "create_", "delete_")) for name, _ in store.calls)


def test_dry_run_never_creates_bucket_or_public_policy(assets):
    _, payload, objects = assets
    store = Store()
    with store.public() as public:
        receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public)
    assert ready is None and receipt["would_create_bucket"]
    assert [name for name, _ in store.calls] == ["head_bucket", "get_bucket_policy"]


@pytest.fixture
def visibility_clock(monkeypatch):
    clock = SimpleNamespace(now=0, sleeps=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(publisher, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    return clock


@pytest.mark.parametrize("operation", ["list_objects_v2", "get_bucket_policy"])
@pytest.mark.parametrize("code", ["NoSuchBucket", "404", ""])
def test_new_bucket_waits_for_visibility_before_publication(assets, monkeypatch, visibility_clock, operation, code):
    _, payload, objects = assets
    store = Store()
    original = getattr(store, operation)
    failures = 2

    def delayed(**kwargs):
        nonlocal failures
        if store.exists and failures:
            store.call(operation, kwargs)
            failures -= 1
            raise _error(code, 404)
        return original(**kwargs)

    monkeypatch.setattr(store, operation, delayed)
    with store.public() as public:
        receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert receipt["created_bucket"] and receipt["status"] == "verified" and ready is not None
    assert visibility_clock.sleeps == [publisher.BUCKET_VISIBILITY_POLL_SECONDS] * 2
    assert sum(name == "create_bucket" for name, _ in store.calls) == 1


def test_new_bucket_visibility_wait_is_bounded_without_writes(assets, monkeypatch, visibility_clock):
    _, payload, objects = assets
    store = Store()
    audit = {}

    def missing(**kwargs):
        store.call("list_objects_v2", kwargs)
        raise _error("NoSuchBucket", 404)

    monkeypatch.setattr(store, "list_objects_v2", missing)
    with store.public() as public, pytest.raises(ClientError, match="NoSuchBucket"):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True, audit=audit)
    assert visibility_clock.now == publisher.BUCKET_VISIBILITY_TIMEOUT_SECONDS
    assert audit["created_bucket"] and audit["uploaded"] == 0 and audit["phase"] == "bucket-admission"
    assert not any(name.startswith("put_") for name, _ in store.calls)


@pytest.mark.parametrize("operation", ["list_objects_v2", "get_bucket_policy"])
@pytest.mark.parametrize("code,status", [("AccessDenied", 403), ("AccessDenied", 404), ("InternalError", 500)])
def test_new_bucket_read_errors_fail_immediately(assets, monkeypatch, visibility_clock, operation, code, status):
    _, payload, objects = assets
    store = Store()

    def denied(**kwargs):
        store.call(operation, kwargs)
        if not store.exists:
            return getattr(Store, operation)(store, **kwargs)
        raise _error(code, status)

    monkeypatch.setattr(store, operation, denied)
    with store.public() as public, pytest.raises(ClientError, match=code):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert not visibility_clock.sleeps
    assert not any(name.startswith("put_") for name, _ in store.calls)


def test_new_bucket_with_content_after_visibility_delay_is_rejected(assets, monkeypatch, visibility_clock):
    _, payload, objects = assets
    store = Store()
    calls = 0

    def nonempty(**kwargs):
        nonlocal calls
        store.call("list_objects_v2", kwargs)
        calls += 1
        if calls == 1:
            raise _error("NoSuchBucket", 404)
        return {"Contents": [{"Key": "unexpected", "Size": 1}]}

    monkeypatch.setattr(store, "list_objects_v2", nonempty)
    with store.public() as public, pytest.raises(ValueError, match="not empty"):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert len(visibility_clock.sleeps) == 1
    assert not any(name.startswith("put_") for name, _ in store.calls)


@pytest.mark.parametrize("operation", ["get_bucket_policy", "get_bucket_acl", "list_objects_v2"])
def test_new_bucket_verification_waits_for_post_policy_visibility(assets, monkeypatch, visibility_clock, operation):
    _, payload, objects = assets
    store = Store()
    original = getattr(store, operation)
    failures = 2

    def delayed(**kwargs):
        nonlocal failures
        if store.policy is not None and failures:
            store.call(operation, kwargs)
            failures -= 1
            raise _error("NoSuchBucket", 404)
        return original(**kwargs)

    monkeypatch.setattr(store, operation, delayed)
    with store.public() as public:
        receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert receipt["status"] == "verified" and ready is not None
    assert len(visibility_clock.sleeps) == 2
    assert sum(name == "create_bucket" for name, _ in store.calls) == 1
    assert sum(name == "put_bucket_policy" for name, _ in store.calls) == 1


@pytest.mark.parametrize("case", ["known-policy", "no-policy", "unexpected-policy", "access-denied"])
def test_stale_head_only_admits_existing_bucket_with_exact_policy(assets, monkeypatch, visibility_clock, case):
    _, payload, objects = assets
    store = Store(exists=True)
    if case == "no-policy":
        store.policy = None
    elif case == "unexpected-policy":
        store.policy["Statement"][0]["Action"] = "s3:*"
    elif case == "access-denied":
        def denied(**kwargs):
            store.call("get_bucket_policy", kwargs)
            raise _error("AccessDenied", 403)
        monkeypatch.setattr(store, "get_bucket_policy", denied)

    def stale_head(**kwargs):
        store.call("head_bucket", kwargs)
        raise _error("404", 404)

    monkeypatch.setattr(store, "head_bucket", stale_head)
    with store.public() as public:
        if case == "known-policy":
            receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public)
            assert not receipt["created_bucket"] and ready is None
        else:
            with pytest.raises((ClientError, ValueError)):
                publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert not visibility_clock.sleeps
    assert not any(name.startswith(("put_", "create_", "delete_")) for name, _ in store.calls)


@pytest.mark.parametrize("operation", ["get_object_acl", "head_object", "get_object"])
@pytest.mark.parametrize("code", ["NoSuchKey", "NoSuchBucket", "404"])
def test_fresh_object_verification_waits_without_repeating_put(assets, monkeypatch, visibility_clock, operation, code):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)
    original = getattr(store, operation)
    failures = 2

    def delayed(**kwargs):
        nonlocal failures
        if failures:
            store.call(operation, kwargs)
            failures -= 1
            raise _error(code, 404)
        return original(**kwargs)

    monkeypatch.setattr(store, operation, delayed)
    publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert len(visibility_clock.sleeps) == 2
    assert sum(name == "put_object" for name, _ in store.calls) == 1


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_bucket_put_retries_preserve_conditional_arguments(assets, monkeypatch, visibility_clock, duplicate):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)
    original = store.put_object
    attempts = []

    def delayed(**kwargs):
        attempts.append(deepcopy(kwargs))
        if len(attempts) == 1:
            # A duplicate outcome must still verify the stored bytes.
            if duplicate:
                original(**kwargs)
            raise _error("NoSuchBucket", 404)
        return original(**kwargs)

    monkeypatch.setattr(store, "put_object", delayed)
    publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert attempts[0]["IfNoneMatch"] == "*" and attempts[0]["ACL"] == "private"
    assert len(visibility_clock.sleeps) == 1
    assert any(name == "get_object" for name, _ in store.calls)


@pytest.mark.parametrize("code,status", [("PreconditionFailed", 412), ("ConditionalRequestConflict", 409)])
def test_conditional_duplicate_verification_shares_put_deadline(assets, monkeypatch, visibility_clock, code, status):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)
    original = store.put_object
    attempts = 0

    def conditional(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _error("404", 404)
        original(**kwargs)
        raise _error(code, status)

    def missing(**kwargs):
        raise _error("NoSuchKey", 404)

    monkeypatch.setattr(store, "put_object", conditional)
    monkeypatch.setattr(store, "head_object", missing)
    with pytest.raises(ClientError, match="NoSuchKey"):
        publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert attempts == 2
    assert visibility_clock.now == publisher.OBJECT_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize("operation", ["put_object", "get_object_acl", "head_object", "get_object"])
def test_fresh_object_missing_resource_wait_is_bounded(assets, monkeypatch, visibility_clock, operation):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)

    def missing(**kwargs):
        store.call(operation, kwargs)
        raise _error("NoSuchBucket", 404)

    monkeypatch.setattr(store, operation, missing)
    with pytest.raises(ClientError, match="NoSuchBucket"):
        publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert visibility_clock.now == publisher.OBJECT_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize("operation", ["put_object", "get_object_acl", "head_object", "get_object"])
@pytest.mark.parametrize("code,status", [("AccessDenied", 403), ("AccessDenied", 404), ("InternalError", 500)])
def test_fresh_object_auth_and_provider_errors_never_retry(assets, monkeypatch, visibility_clock, operation, code, status):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)

    def failed(**kwargs):
        store.call(operation, kwargs)
        raise _error(code, status)

    monkeypatch.setattr(store, operation, failed)
    with pytest.raises(ClientError, match=code):
        publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert not visibility_clock.sleeps
    assert sum(name == "put_object" for name, _ in store.calls) == 1


@pytest.mark.parametrize("case", ["metadata", "content", "acl"])
def test_fresh_object_identity_and_acl_failures_never_retry(assets, monkeypatch, visibility_clock, case):
    _, _, objects = assets
    filename, image = next(iter(objects.items()))
    store = Store(exists=True)
    original = store.put_object

    def corrupt(**kwargs):
        original(**kwargs)
        if case == "metadata":
            store.objects[kwargs["Key"]]["sha256"] = "invalid"
        elif case == "content":
            store.objects[kwargs["Key"]]["data"] = b"x" * image["size"]
        else:
            store.acl["Grants"] = []

    monkeypatch.setattr(store, "put_object", corrupt)
    with pytest.raises(ValueError):
        publisher._put_missing_object(store, store.bucket, NEWSLETTER_S3_PREFIX + filename, image)
    assert not visibility_clock.sleeps
    assert sum(name == "put_object" for name, _ in store.calls) == 1


def _existing_verification_store(objects, kind):
    store = Store(exists=True)
    if kind == "image":
        filename, image = next(iter(objects.items()))
        key = NEWSLETTER_S3_PREFIX + filename
    else:
        key = PRIVATE_PROBE_KEY
        image = {"data": publisher.PRIVATE_PROBE_BYTES, "content_type": "application/octet-stream",
                 "sha256": hashlib.sha256(publisher.PRIVATE_PROBE_BYTES).hexdigest()}
    store.objects[key] = deepcopy(image)
    return store, key


@pytest.mark.parametrize("kind", ["image", "sentinel"])
@pytest.mark.parametrize("operation", ["get_object_acl", "head_object", "get_object"])
@pytest.mark.parametrize("expires", [False, True])
def test_existing_object_verification_retries_missing_reads_with_bound(assets, monkeypatch, visibility_clock, kind, operation, expires):
    _, payload, objects = assets
    store, key = _existing_verification_store(objects, kind)
    original = getattr(store, operation)
    failures = 2

    def delayed(**kwargs):
        nonlocal failures
        if kwargs["Key"] == key and (expires or failures):
            store.call(operation, kwargs)
            failures -= 1
            raise _error("NoSuchBucket", 404)
        return original(**kwargs)

    monkeypatch.setattr(store, operation, delayed)
    with store.public() as public:
        if expires:
            with pytest.raises(ClientError, match="NoSuchBucket"):
                publish_to_s3(payload, objects, environment="development", client=store, public=public)
            assert visibility_clock.now == publisher.OBJECT_VISIBILITY_TIMEOUT_SECONDS
        else:
            receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public)
            assert ready is None and receipt["existing"] == (1 if kind == "image" else 0)
            assert len(visibility_clock.sleeps) == 2
    assert not any(name.startswith(("put_", "create_", "delete_")) for name, _ in store.calls)


@pytest.mark.parametrize("kind", ["image", "sentinel"])
@pytest.mark.parametrize("case", ["content", "acl"])
def test_existing_object_content_and_acl_mismatch_fail_without_retry(assets, monkeypatch, visibility_clock, kind, case):
    _, payload, objects = assets
    store, key = _existing_verification_store(objects, kind)
    if case == "content":
        store.objects[key]["data"] = b"x" * len(store.objects[key]["data"])
    else:
        def public_acl(**kwargs):
            store.call("get_object_acl", kwargs)
            return {"Owner": {"ID": "newsletter-owner"}, "Grants": []}
        monkeypatch.setattr(store, "get_object_acl", public_acl)
    with store.public() as public, pytest.raises(ValueError):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert not visibility_clock.sleeps
    assert not any(name.startswith(("put_", "create_", "delete_")) for name, _ in store.calls)


@pytest.mark.parametrize("operation", ["get_bucket_policy", "get_bucket_acl", "list_objects_v2"])
@pytest.mark.parametrize("phase", ["admission", "final"])
@pytest.mark.parametrize("expires", [False, True])
def test_existing_bucket_read_checks_have_bounded_fresh_deadlines(assets, monkeypatch, visibility_clock, operation, phase, expires):
    _, payload, objects = assets
    store = Store(exists=True)
    original = getattr(store, operation)
    public_boundary = publisher.verify_public_boundary
    final = False
    failures = 1

    def boundary(*args):
        nonlocal final
        public_boundary(*args)
        # Uploads/public verification can outlive the admission deadline.
        visibility_clock.now += 60
        final = True

    def delayed(**kwargs):
        nonlocal failures
        if final == (phase == "final") and (expires or failures):
            store.call(operation, kwargs)
            failures -= 1
            raise _error("NoSuchBucket", 404)
        return original(**kwargs)

    monkeypatch.setattr(publisher, "verify_public_boundary", boundary)
    monkeypatch.setattr(store, operation, delayed)
    with store.public() as public:
        if expires:
            with pytest.raises(ClientError, match="NoSuchBucket"):
                publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
            assert visibility_clock.now == (60 if phase == "final" else 0) + publisher.BUCKET_VISIBILITY_TIMEOUT_SECONDS
        else:
            receipt, ready = publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
            assert receipt["status"] == "verified" and ready is not None
            assert len(visibility_clock.sleeps) == 1
    assert not any(name in {"create_bucket", "put_bucket_policy"} for name, _ in store.calls)


@pytest.mark.parametrize("case", ["wrong-bucket", "endpoint", "region", "missing-image", "extra-image", "tampered-bytes"])
def test_all_scope_and_local_validation_precedes_provider_calls(assets, case):
    _, payload, objects = assets
    store = Store()
    environment = "development"
    if case == "wrong-bucket":
        environment = "unrelated-bucket"
    elif case == "endpoint":
        store.meta.endpoint_url = "https://other.example"
    elif case == "region":
        store.meta.region_name = "fsn1"
    elif case == "missing-image":
        objects = {}
    elif case == "extra-image":
        objects = {**objects, "not-authorized.jpg": next(iter(objects.values()))}
    else:
        next(iter(objects.values()))["data"] = b"tampered"
    with store.public() as public, pytest.raises(ValueError):
        publish_to_s3(payload, objects, environment=environment, client=store, public=public, apply=True)
    assert not store.calls


@pytest.mark.parametrize("case", ["no-policy", "broad-policy", "unrelated-resource", "extra-statement", "public-acl", "unrelated-object"])
def test_existing_unexpected_bucket_is_never_adopted_or_mutated(assets, case):
    _, payload, objects = assets
    store = Store(exists=True)
    if case == "no-policy":
        store.policy = None
    elif case == "broad-policy":
        store.policy["Statement"][0]["Action"] = "s3:*"
    elif case == "unrelated-resource":
        store.policy["Statement"][0]["Resource"] = "arn:aws:s3:::private-bucket/*"
    elif case == "extra-statement":
        store.policy["Statement"].append(deepcopy(store.policy["Statement"][0]))
    elif case == "public-acl":
        store.acl["Grants"].append({"Permission": "READ", "Grantee": {"Type": "Group", "URI": "AllUsers"}})
    else:
        store.objects["private/unrelated.txt"] = {"data": b"unrelated"}
    with store.public() as public, pytest.raises((ValueError, ClientError)):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert not any(name.startswith(("put_", "create_", "delete_")) for name, _ in store.calls)
    assert not any(name == "get_object" for name, _ in store.calls)


def test_existing_changed_object_never_gets_overwritten(assets):
    _, payload, objects = assets
    store = Store(exists=True)
    filename, image = next(iter(objects.items()))
    store.objects[NEWSLETTER_S3_PREFIX + filename] = {**image, "data": b"x" * image["size"]}
    with store.public() as public, pytest.raises(ValueError, match="content differs"):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True)
    assert not any(name == "put_object" for name, _ in store.calls)


@pytest.mark.parametrize("unsafe", ["list", "private-prefix", "write", "image"])
def test_failed_public_boundary_never_returns_ready_manifest(assets, unsafe):
    _, payload, objects = assets
    store = Store()
    audit = {}
    with store.public(unsafe=unsafe) as public, pytest.raises(ValueError):
        publish_to_s3(payload, objects, environment="development", client=store, public=public, apply=True, audit=audit)
    assert "s3_publications" not in payload and audit["phase"] == "public-boundary-verification"


@pytest.mark.parametrize("case", ["file-symlink", "directory-symlink", "bad-size", "bad-name"])
def test_staged_manifest_path_and_hash_validation_is_fail_closed(assets, tmp_path, case):
    root, payload, objects = assets
    filename = next(iter(objects))
    path = root / STATIC_DIR / filename
    if case == "file-symlink":
        saved = tmp_path / "outside.jpg"
        saved.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(saved)
    elif case == "directory-symlink":
        directory = path.parent
        saved = directory.with_name("outside-assets")
        directory.rename(saved)
        directory.symlink_to(saved, target_is_directory=True)
    elif case == "bad-size":
        path.write_bytes(b"truncated")
    else:
        payload["assets"]["campaign/header.png"]["filename"] = "../../unrelated.jpg"
        atomic_json(root / ASSET_MAP_PATH, payload)
    with pytest.raises(ValueError):
        validated_local_assets(root)


def test_official_nbg1_endpoint_override_is_equivalent_and_other_endpoints_fail(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://nbg1.your-objectstorage.com")
    assert newsletter_s3_endpoint() == "https://nbg1.your-objectstorage.com"
    for endpoint in ("https://fsn1.your-objectstorage.com", "https://unrelated.example", "http://storage.ci.test:9000"):
        monkeypatch.setenv("S3_ENDPOINT_URL", endpoint)
        monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
        with pytest.raises(ValueError, match="exact isolated CI"):
            newsletter_s3_endpoint()


@pytest.mark.parametrize("endpoint", [None, "https://nbg1.your-objectstorage.com", "http://unrelated:9000"])
def test_ci_can_never_fall_back_to_live_publication(monkeypatch, endpoint):
    for key, value in {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
                       "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development"}.items():
        monkeypatch.setenv(key, value)
    if endpoint is None:
        monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    else:
        monkeypatch.setenv("S3_ENDPOINT_URL", endpoint)
    with pytest.raises(ValueError, match="exact isolated CI"):
        newsletter_s3_endpoint()
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    assert newsletter_s3_endpoint() == "http://storage.ci.test:9000"


@pytest.mark.parametrize("indicator", ["CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_MAIL_CAPTURE"])
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " on "])
def test_any_ci_indicator_prevents_live_endpoint(monkeypatch, indicator, value):
    for key in ("CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_MAIL_CAPTURE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(indicator, value)
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://nbg1.your-objectstorage.com")
    with pytest.raises(ValueError, match="exact isolated CI"):
        newsletter_s3_endpoint()


@pytest.mark.parametrize("content", [
    '<style>@import "https://evil.test/style.css";</style>',
    '<animate attributeName="href" values="javascript:alert(1)"/>',
    '<set attributeName="href" to="https://evil.test/image"/>',
    '<image href="https://evil.test/image"/>',
    '<script>alert(1)</script>',
    '<?xml-stylesheet href="https://evil.test/style.css"?>',
])
def test_svg_rejects_external_or_active_content(content):
    data = f'<svg xmlns="http://www.w3.org/2000/svg">{content}</svg>'.encode()
    filename = hashlib.sha256(data).hexdigest() + ".svg"
    with pytest.raises(ValueError):
        validate_image_bytes(filename, data, {"size_bytes": len(data)})
