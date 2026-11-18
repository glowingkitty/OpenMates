# contract-test-file: infrastructure
# backend/tests/fake_figma_api.py
#
# Stateful fake Figma REST API (httpx transport) serving a synthetic file,
# nodes, image exports and local variables, with a request log and
# configurable failures.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "figma"
FILE_KEY = "AbCdEf1234567890"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def find_node(node: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    if node.get("id") == node_id:
        return node
    for child in node.get("children") or []:
        found = find_node(child, node_id)
        if found:
            return found
    return None


@dataclass
class FakeFigmaApi:
    access_token: str = "synthetic-figma-token"
    file: dict[str, Any] = field(default_factory=lambda: load_fixture("synthetic_landing_file.json"))
    variables: dict[str, Any] = field(default_factory=lambda: load_fixture("synthetic_variables.json"))
    variables_plan_limited: bool = False
    rate_limit: dict[str, str] | None = None
    fail_next: list[httpx.Response | Exception] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client_factory(self):
        from backend.shared.providers.figma.client import FigmaClient

        def build(*, access_token: str) -> FigmaClient:
            return FigmaClient(access_token=access_token, transport=self.transport)

        return build

    def calls(self, kind: str) -> list[httpx.Request]:
        return [r for r in self.requests if self._kind(r.url.path) == kind]

    @staticmethod
    def _kind(path: str) -> str:
        if path.startswith("/v1/images/"):
            return "images"
        if path.endswith("/variables/local"):
            return "variables"
        if path.endswith("/nodes"):
            return "nodes"
        return "file"

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            failure = self.fail_next.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        if request.headers.get("authorization") != f"Bearer {self.access_token}":
            return httpx.Response(401, json={"status": 401, "err": "Invalid token"})
        if self.rate_limit is not None:
            return httpx.Response(429, headers=self.rate_limit, json={"status": 429, "err": "Rate limit exceeded"})
        parts = request.url.path.strip("/").split("/")
        if len(parts) < 3 or parts[2] != FILE_KEY:
            return httpx.Response(404, json={"status": 404, "err": "Not found"})
        kind = self._kind(request.url.path)
        params = request.url.params
        if kind == "file":
            return httpx.Response(200, json=copy.deepcopy(self.file))
        if kind == "variables":
            if self.variables_plan_limited:
                return httpx.Response(403, json={"status": 403, "error": True, "message": "Limited by Figma plan"})
            return httpx.Response(200, json=self.variables)
        ids = [i for i in params.get("ids", "").split(",") if i]
        if kind == "nodes":
            root = self.file["document"]
            nodes = {}
            for node_id in ids:
                found = find_node(root, node_id)
                nodes[node_id] = None if found is None else {
                    "document": copy.deepcopy(found), "components": self.file["components"],
                    "componentSets": {}, "styles": self.file["styles"],
                }
            return httpx.Response(200, json={
                "name": self.file["name"], "lastModified": self.file["lastModified"],
                "version": self.file["version"], "nodes": nodes,
            })
        fmt = params.get("format", "png")
        return httpx.Response(200, json={"err": None, "images": {
            i: f"https://figma-alpha-api.s3.example.org/img/{i.replace(':', '-')}.{fmt}" for i in ids
        }})
