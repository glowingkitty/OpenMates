"""Private facade mock draft; never establishes native source implementation proof."""

import asyncio
import json
from types import SimpleNamespace
import pytest
from openmates import OpenMatesProjectSourceAuthoringUnavailableError
from openmates.session_client import SessionClient, SessionProjects, SessionClientError


def facade_client(native):
    """Real SessionClient dispatch path over a fake native object."""
    client = SessionClient.__new__(SessionClient)
    client._essential_epoch = 0
    client._native = native
    return client

METADATA = {
    "root": "/synthetic",
    "binding_root": "/synthetic",
    "teamId": {"updatedAt": 1, "config": {"sourceId": "unchanged"}},
    "__proto__": {"kept": True},
    "a.b/c": [{"scopeIn": "unchanged"}],
}


def source():
    return dict(
        source_id="source",
        source_type="local_folder",
        display_name="Synthetic",
        metadata=METADATA,
        capabilities=[],
        status="offline",
        created_at=1,
        updated_at=2,
        last_indexed_at=None,
    )


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_source_metadata_and_legacy_capabilities_are_preserved():
    async def run():
        seen = []

        async def create(*args):
            seen.append(args)
            return args[1]

        async def update(*args):
            seen.append(args)
            return json.dumps(
                dict(metadata=METADATA, capabilities=["read"], updated_at=3)
            )

        async def call(operation):
            return await operation()

        projects = SessionProjects(
            facade_client(
                SimpleNamespace(
                    projects_create_source=create,
                    projects_update_source_capabilities=update,
                )
            )
        )
        result = await projects.create_source(
            "project", source(), filters={"personal": True}
        )
        assert result["metadata"] == METADATA
        duplicate = source()
        duplicate["capabilities"] = ["read", "read"]
        await projects.create_source("project", duplicate, filters={"team_id": "team"})
        assert json.loads(seen[1][1])["capabilities"] == ["read", "read"]
        result = await projects.update_source_capabilities(
            "project",
            "literal%2F",
            {"capabilities": ["read"], "updated_at": 3},
            filters={"personal": True},
        )
        assert result["metadata"] == METADATA
        assert json.loads(seen[2][2]) == {"capabilities": ["read"], "updated_at": 3}

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_source_invalid_metadata_is_static_and_pre_native():
    async def run():
        calls = []

        async def native(*args):
            calls.append(args)
            raise AssertionError("unexpected")

        async def call(operation):
            return await operation()

        projects = SessionProjects(
            facade_client(SimpleNamespace(projects_create_source=native))
        )
        cycle = {}
        cycle["self"] = cycle
        for metadata in [
            [],
            {"value": float("nan")},
            {1: "private-secret"},
            cycle,
            {"value": "x" * (1024 * 1024 + 1)},
        ]:
            value = source()
            value["metadata"] = metadata
            with pytest.raises(SessionClientError) as caught:
                await projects.create_source(
                    "project", value, filters={"personal": True}
                )
            assert caught.value.code == "invalid_argument"
            assert str(caught.value) == "Invalid typed Project source input."
        assert calls == []

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_key_source_authoring_refuses_without_transport(monkeypatch):
    # These namespace methods do not inspect the client, even for malformed input.
    from openmates.sdk import OpenMatesProjects

    client = SimpleNamespace()
    projects = OpenMatesProjects(client)
    for call in [
        lambda: projects.create_source("project", source(), filters={"personal": True}),
        lambda: projects.update_source_capabilities(
            "project", "source", {}, filters={"personal": True}
        ),
    ]:
        with pytest.raises(OpenMatesProjectSourceAuthoringUnavailableError) as caught:
            call()
        assert caught.value.code == "project_source_authoring_unavailable"
        assert caught.value.reason == "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION"


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_compact_numeric_metadata_is_not_rejected_by_inflated_estimate():
    from openmates.project_sources import source_json

    value = source()
    value["metadata"] = {"numbers": [0] * 32000}
    assert json.loads(source_json(value))["metadata"] == value["metadata"]
