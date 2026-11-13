"""Embed Project link/unlink resolve non-UUID selectors before routing (npm/Rust parity)."""
# contract-test-file: tooling
import pytest

from openmates import sdk

PROJECT_ID = "22222222-2222-4222-8222-222222222222"


class _Projects:
    def __init__(self):
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return [{"project_id": PROJECT_ID, "slug": "launch-plan", "name": "Launch Plan"}]


class _Client:
    def __init__(self):
        self.projects = _Projects()


@pytest.mark.parametrize("selector", ["launch-plan", "Launch Plan", "22222222"])
def test_add_and_remove_route_to_the_resolved_project_id(selector, monkeypatch):
    client = _Client()
    routed = []
    monkeypatch.setattr(sdk, "_resolve_project_key", lambda _client, project_id: routed.append(("key", project_id)) or b"k" * 32)
    monkeypatch.setattr(sdk, "_create_encrypted_project_item", lambda _client, project_id, _key, **_kw: routed.append(("add", project_id)) or {"ok": True})
    monkeypatch.setattr(sdk, "_delete_project_item_by_target", lambda _client, project_id, item_type, target: routed.append(("remove", project_id, item_type, target)) or {"deleted": True})
    embeds = sdk.OpenMatesEmbeds(client)
    embeds.add_to_project("embed-a", selector)
    embeds.remove_from_project("embed-a", selector)
    assert routed == [("key", PROJECT_ID), ("add", PROJECT_ID), ("remove", PROJECT_ID, "embed", "embed-a")]
    assert client.projects.calls == 2


def test_canonical_uuid_selector_skips_project_listing(monkeypatch):
    client = _Client()
    monkeypatch.setattr(sdk, "_resolve_project_key", lambda _client, project_id: b"k" * 32)
    monkeypatch.setattr(sdk, "_create_encrypted_project_item", lambda _client, project_id, _key, **_kw: {"project_id": project_id})
    assert sdk.OpenMatesEmbeds(client).add_to_project("embed-a", PROJECT_ID) == {"project_id": PROJECT_ID}
    assert client.projects.calls == 0
