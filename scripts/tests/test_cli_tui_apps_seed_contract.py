"""Validate the terminal proof's actual encrypted fixture against the save API model."""
# contract-test-file: infrastructure
from __future__ import annotations

import ast
import base64
import binascii
import json
from pathlib import Path
import re
import subprocess
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]


def test_terminal_apps_seed_matches_actual_save_graph_contract():
    source = (ROOT / "frontend/apps/web_app/tests/cli-tui-proof-helpers.ts").read_text()
    block = source.split("function seedEncryptedAppsResult(", 1)[1].split("].join('\\n');", 1)[0]
    program = "\n".join(json.loads(line.strip().removesuffix(","))
                        for line in block.splitlines() if line.strip().startswith('"'))
    # Execute the exact fixture construction and AES-GCM encryption, with no product transport.
    program = program.replace(
        "const {OpenMatesClient}=await import(pathToFileURL(root+'/index.js').href);",
        "let payload; const OpenMatesClient={load:()=>({"
        "whoAmI:async()=>({id:'00000000-0000-4000-8000-000000000001'}),"
        "getActiveTeamId:()=>null,getMasterKeyBytes:()=>Buffer.alloc(32,7),"
        "saveAppsWorkspaceResult:async value=>{payload=value;},"
        "getAppsWorkspaceResult:async()=>({children:payload.embeds.slice(1)})})};",
    ).replace("process.stdout.write(embedId);", "process.stdout.write(JSON.stringify(payload));")
    result = subprocess.run(["node", "--input-type=module", "-e", program, "/synthetic"],
                            capture_output=True, text=True, check=True, timeout=15)
    payload = json.loads(result.stdout)

    # Load only the actual request-model definitions; avoid booting API dependencies.
    schema_path = ROOT / "backend/core/api/app/routes/apps_workspace.py"
    tree = ast.parse(schema_path.read_text())
    definitions = [node for node in tree.body if
                   isinstance(node, (ast.FunctionDef, ast.ClassDef))
                   and node.name in {"_ciphertext", "EncryptedResultEmbed", "SaveAppsResult"}
                   or isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "_APP_ID" for target in node.targets)]
    namespace = dict(base64=base64, binascii=binascii, re=re, UUID=UUID, Literal=Literal,
                     BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
                     field_validator=field_validator, model_validator=model_validator)
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(schema_path), "exec"), namespace)
    for name in ["EncryptedResultEmbed", "SaveAppsResult"]:
        namespace[name].model_rebuild(_types_namespace=namespace)
    validated = namespace["SaveAppsResult"].model_validate(payload)
    assert validated.linked_embed_ids == []
    assert len(validated.embeds) == 2
    parent, child = validated.embeds
    assert parent.embed_id == validated.root_embed_id
    assert parent.embed_ids == [child.embed_id]
    assert child.parent_embed_id == parent.embed_id
    assert child.embed_id != parent.embed_id

    def open_ciphertext(value: str, key: bytes) -> bytes:
        packed = base64.b64decode(value)
        return AESGCM(key).decrypt(packed[:12], packed[12:], None)

    embed_key = open_ciphertext(validated.encrypted_embed_key, bytes([7]) * 32)
    root_content = json.loads(open_ciphertext(parent.encrypted_content, embed_key))
    child_content = json.loads(open_ciphertext(child.encrypted_content, embed_key))
    assert root_content["embed_ids"] == [str(child.embed_id)]
    assert open_ciphertext(child.encrypted_type, embed_key) == b"web-website"
    assert child_content == {
        "title": "Terminal proof saved result",
        "url": "https://example.test/terminal-proof",
        "description": "Synthetic child website with useful search context.",
    }
    assert "Terminal proof saved result" not in result.stdout
    assert "https://example.test" not in result.stdout
