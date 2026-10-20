"""Scoped standing human instructions about repeated approval ceremony.

This is not approval of Specification fingerprints or verification evidence.
Original user provenance is checked at export. A private exact-digest export can
carry that same evidence to a replacement administrative session on another host;
import/gate validation checks the evidence again, never inventing remote history.
Session metadata owns bindings; private artifacts retain the original message.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import yaml

try:
    from . import _workflow_decisions as decisions
except ImportError:
    import _workflow_decisions as decisions

SURFACE = "specification-approval-prompt"
KIND = "verified-specification-approval-prompt-waiver"
STATE_KEY = "specification_approval_prompt_waivers"
MAX_EVIDENCE_BYTES = 128 * 1024


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def task_id(session: dict) -> str:
    value = session.get("task_id")
    if isinstance(value, str) and value:
        return value
    match = re.match(r"^(TASK-[0-9]+)(?:\b|:)", str(session.get("task") or ""))
    if not match:
        raise ValueError("Waiver requires the session's explicit existing Task identity")
    return match.group(1)


def plan_scope(root: Path, relative: str) -> dict:
    root = root.resolve()
    path = (root / relative).resolve()
    if path.name != "plan.yml" or not path.is_relative_to(root / "docs/plans"):
        raise ValueError("Waiver Plan must be an owning repository Plan")
    plan = yaml.safe_load(path.read_text())
    if not isinstance(plan, dict) or not plan.get("id") or not plan.get("task"):
        raise ValueError("Waiver Plan requires its existing id and Task")
    allowed = set()
    seen = set()
    standing_instruction = False
    pending = [path]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        if len(seen) >= 64:
            raise ValueError("Waiver Plan reference scope is too large")
        seen.add(current)
        value = yaml.safe_load(current.read_text())
        if not isinstance(value, dict):
            raise ValueError("Invalid referenced Plan")
        note = value.get("approval_prompt_waiver")
        if value.get("task") == plan["task"] and isinstance(note, dict) and note.get("source") and note.get("instruction"):
            standing_instruction = True
        for ref in value.get("specification_refs", []):
            if isinstance(ref, dict) and isinstance(ref.get("id"), str):
                allowed.add(ref["id"])
        for ref in value.get("references", []):
            if not isinstance(ref, str):
                continue
            target = (root / ref).resolve()
            if target.is_relative_to(root / "docs/plans") and target.name == "plan.yml" and target.is_file():
                pending.append(target)
            elif target.is_relative_to(root / "specifications") and target.name == "specification.yml" and target.is_file():
                spec = yaml.safe_load(target.read_text())
                if isinstance(spec, dict) and isinstance(spec.get("id"), str):
                    allowed.add(spec["id"])
    if not standing_instruction:
        raise ValueError("Owning Plan scope has no retained standing approval-prompt instruction")
    return {"plan_path": path.relative_to(root).as_posix(), "plan_id": plan["id"],
            "task_id": plan["task"], "referenced_specifications": sorted(allowed)}


def build_export(root: Path, session_id: str, session: dict, *, plan: str,
                 specifications: list[str], source: dict, quote: str, read_message=None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        raise ValueError("Invalid owning session")
    context = plan_scope(root, plan)
    selected = sorted(set(specifications))
    if not selected or not set(selected).issubset(context["referenced_specifications"]):
        raise ValueError("Waiver scope must name only explicitly referenced Specifications")
    if task_id(session) != context["task_id"] or source.get("session_id") != session.get("codex_task_id"):
        raise ValueError("Human source and Plan must belong to the owning session and Task")
    message = (read_message or decisions.read_user_message)(source)
    if message.get("role") != "user" or not quote.strip() or quote not in message.get("text", ""):
        raise ValueError("Waiver needs the exact original human instruction")
    if hashlib.sha256(message["text"].encode()).hexdigest() != source.get("message_id"):
        raise ValueError("Original human message identity does not match")
    scope = {"originating_session": session_id, "task_id": context["task_id"],
             "plan_path": context["plan_path"], "plan_id": context["plan_id"],
             "specification_ids": selected}
    record = decisions.make_receipt(target=context["task_id"], surface=SURFACE,
        revision=digest(scope), decision="waive", source=source, quote=quote,
        read_message=lambda _: message)
    return {"schema_version": 1, "kind": KIND, "scope": scope, "decision": record,
            "evidence": {"role": "user", "text": message["text"], "quote": quote},
            "meaning": "Standing approval-prompt waiver only; no exact-fingerprint approval or proof claimed"}


def validate_export(value: dict) -> dict:
    if value.get("schema_version") != 1 or value.get("kind") != KIND:
        raise ValueError("Unsupported waiver evidence")
    scope = value.get("scope", {})
    record = value.get("decision", {})
    evidence = value.get("evidence", {})
    if (not isinstance(scope, dict) or not isinstance(record, dict) or not isinstance(evidence, dict)
            or not all(isinstance(scope.get(k), str) and scope[k] for k in
                       ["originating_session", "task_id", "plan_path", "plan_id"])
            or not isinstance(scope.get("specification_ids"), list)
            or not scope["specification_ids"]
            or scope["specification_ids"] != sorted(set(scope["specification_ids"]))):
        raise ValueError("Invalid waiver scope")
    source = record.get("source", {})
    if (source.get("provider") != "codex" or evidence.get("role") != "user"
            or not isinstance(evidence.get("text"), str) or not isinstance(evidence.get("quote"), str)
            or not evidence["quote"].strip() or evidence["quote"] not in evidence["text"]
            or hashlib.sha256(evidence["text"].encode()).hexdigest() != source.get("message_id")
            or source.get("text_sha256") != source.get("message_id")):
        raise ValueError("Invalid original human evidence")
    expected = decisions.make_receipt(target=scope["task_id"], surface=SURFACE,
        revision=digest(scope), decision="waive", source=source, quote=evidence["quote"],
        read_message=lambda _: {"role": evidence["role"], "text": evidence["text"]})
    for key in ["id", "status", "target", "surface", "revision", "decision", "source"]:
        if record.get(key) != expected[key]:
            raise ValueError("Waiver decision does not match its exact scope and human provenance")
    return scope


def write_private(path: Path, data: bytes) -> None:
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ValueError("Waiver evidence exceeds its private bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        os.chmod(temporary, 0o600)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def evidence_path(control_root: Path, sha256: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Invalid evidence artifact identity")
    return control_root / "logs/workflow-decisions/specification-approval-prompt" / (sha256 + ".json")


def import_export(control_root: Path, artifact: Path, expected_sha256: str,
                  session_id: str, session: dict) -> dict:
    if artifact.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError("Waiver evidence exceeds its private bounded size")
    data = artifact.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Transferred human evidence does not match the verified source export")
    value = json.loads(data)
    scope = validate_export(value)
    if task_id(session) != scope["task_id"]:
        raise ValueError("Cannot carry the standing instruction into another Task")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        raise ValueError("Invalid replacement session")
    binding = {"kind": KIND, "status": "active", "session_id": session_id,
               "task_id": scope["task_id"], "evidence_sha256": expected_sha256,
               "originating_session": scope["originating_session"], "decision_id": value["decision"]["id"]}
    binding["binding_id"] = digest(binding)
    # Original text remains a private evidence artifact, never session JSON,
    # approval state, generated metadata, tracked source or stdout.
    write_private(evidence_path(control_root, expected_sha256), data)
    return binding


def permits_prompt_waiver(repo_root: Path, control_root: Path, session_id: str,
                          specification_id: str) -> bool:
    try:
        state = json.loads((control_root / ".claude/sessions.json").read_text())
        session = state.get("sessions", {}).get(session_id, {})
        owner_task = task_id(session)
        for binding in reversed(session.get(STATE_KEY, [])):
            if not isinstance(binding, dict):
                continue
            unsigned = {k: v for k, v in binding.items() if k != "binding_id"}
            if (binding.get("kind") != KIND or binding.get("status") != "active"
                    or binding.get("session_id") != session_id or binding.get("task_id") != owner_task
                    or binding.get("binding_id") != digest(unsigned)):
                continue
            path = evidence_path(control_root, binding.get("evidence_sha256", ""))
            if path.stat().st_size > MAX_EVIDENCE_BYTES:
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != binding["evidence_sha256"]:
                continue
            value = json.loads(data)
            scope = validate_export(value)
            if (scope["task_id"] != owner_task or scope["originating_session"] != binding["originating_session"]
                    or value["decision"]["id"] != binding["decision_id"]
                    or specification_id not in scope["specification_ids"]):
                continue
            current = plan_scope(repo_root, scope["plan_path"])
            if (current["task_id"] == owner_task and current["plan_id"] == scope["plan_id"]
                    and specification_id in current["referenced_specifications"]):
                return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
        pass
    return False
