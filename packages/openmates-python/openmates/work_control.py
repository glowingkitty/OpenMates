"""Shared structured work-control facades for the Python SDK.

Purpose: keep Plan and Task dependency operations consistent with the npm SDK.
Architecture: these facades delegate to the owning SDK namespace for ID resolution.
Security: they only transport encrypted work records and safe dependency metadata.
Spec: docs/specs/opencode-openmates-work-control/spec.yml.
"""

from __future__ import annotations

from typing import Any


class WorkDependenciesFacade:
    def __init__(self, client: Any, kind: str):
        self._client = client
        self._kind = kind

    def add(self, source_id: str, target: dict[str, str]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-{self._kind}s/{source_id}/dependencies", {"target_ref": f"{target['kind']}:{target['id']}"})

    def remove(self, source_id: str, target: dict[str, str]) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-{self._kind}s/{source_id}/dependencies/{target['kind']}/{target['id']}")

    def list(self, source_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/user-{self._kind}s/{source_id}/dependencies")
