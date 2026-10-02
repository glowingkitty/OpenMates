#!/usr/bin/env python3
# contract-test-file: tooling
"""Inspect one private saved Hosting chat graph after its dev deployment.

Default graph inspection is read-only. With --require-sdk, the probe may
approve only the named disposable npm/pip test devices for the supplied API
key. It never sends a chat message, creates an API key, or shares an embed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit

from test_hosting_requirements import (
    CLI_DIST, DEFAULT_API_URL, LOGIN_HELPER, ProbeFailure, ROOT, _run, _test_account_env,
)
from test_hosting_social_chat import _cli, _embed_ids


def _ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ProbeFailure(f"{label} must be a decoded list of child IDs")
    if len(value) != len(set(value)):
        raise ProbeFailure(f"{label} contains duplicate child IDs")
    return value


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProbeFailure(f"{label} is outside its contract bounds")
    return value


def _child_payload(embed: dict[str, Any]) -> dict[str, Any]:
    if embed.get("appId") != "hosting" or embed.get("type") != "hosting_domain":
        raise ProbeFailure("A checked child is not a Hosting domain embed")
    content = embed.get("content")
    if not isinstance(content, dict):
        raise ProbeFailure("A Hosting domain child has no decoded content")
    if (content.get("type"), content.get("app_id"), content.get("skill_id")) != (
        "hosting_domain", "hosting", "search_domains"
    ):
        raise ProbeFailure("A Hosting domain child lost its canonical identity")
    payload = content
    name = payload.get("domain_ascii")
    if not isinstance(name, str) or "." not in name or name != name.lower():
        raise ProbeFailure("A checked domain has no canonical ASCII name")
    try:
        name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProbeFailure("A checked domain did not preserve IDNA ASCII") from exc
    if not isinstance(payload.get("domain_unicode"), str):
        raise ProbeFailure("A checked domain has no Unicode display name")
    if payload.get("availability") not in {"available", "unavailable", "unknown"}:
        raise ProbeFailure("A checked domain has an invalid availability state")
    if not isinstance(payload.get("checked_at"), str) or not payload["checked_at"]:
        raise ProbeFailure("A checked domain lost its check time")
    if payload.get("provider") != "Gandi":
        raise ProbeFailure("A checked domain lost its provider evidence")
    for field in ("registration_tiers", "renewal_tiers"):
        tiers = payload.get(field)
        if not isinstance(tiers, list):
            raise ProbeFailure("A checked domain lost quote tier arrays")
        for tier in tiers:
            if not isinstance(tier, dict) or not isinstance(tier.get("duration_range"), dict):
                raise ProbeFailure("A checked domain quote lost its term")
            for price_field in ("price_excluding_tax", "price_including_tax", "normal_price"):
                amount = tier.get(price_field)
                if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float))
                                           or not math.isfinite(amount) or amount < 0):
                    raise ProbeFailure("A checked domain has an invalid quote amount")
    if not isinstance(payload.get("registration_tiers"), list) or not isinstance(payload.get("renewal_tiers"), list):
        raise ProbeFailure("A checked domain lost registration or renewal context")
    return payload


def _validate_parent(parent: dict[str, Any], load_child: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    if (parent.get("appId"), parent.get("skillId"), parent.get("type")) != (
        "hosting", "search_domains", "app_skill_use"
    ):
        raise ProbeFailure("Saved search parent identity is incorrect")
    content = parent.get("content")
    if not isinstance(content, dict):
        raise ProbeFailure("Saved search parent has no decoded content")
    if (content.get("app_id"), content.get("skill_id"), content.get("provider")) != (
        "hosting", "search_domains", "Gandi"
    ):
        raise ProbeFailure("Saved search parent lost its provider identity")
    if content.get("status") != "finished" or not isinstance(content.get("checked_at"), str):
        raise ProbeFailure("Saved search parent lacks finished or checked state")
    checked_ids = _ids(content.get("embed_ids"), "checked embed_ids")
    selected_ids = _ids(content.get("selected_embed_ids"), "selected_embed_ids")
    if len(checked_ids) > 40:
        raise ProbeFailure("Checked child count is outside the bounded pool")
    max_results = _integer(content.get("max_results"), "max_results", 1, 20)
    if len(selected_ids) > max_results or not set(selected_ids).issubset(checked_ids):
        raise ProbeFailure("Selected child references violate count or checked subset")
    if _integer(content.get("result_count"), "result_count", 0, 20) != len(selected_ids):
        raise ProbeFailure("Parent result count does not match selected children")
    if _integer(content.get("checked_count"), "checked_count", 0, 40) != len(checked_ids):
        raise ProbeFailure("Parent checked count does not match child references")
    if not isinstance(content.get("partial"), bool) or not isinstance(content.get("warnings"), list):
        raise ProbeFailure("Parent partial or warning state is missing")
    if any(not isinstance(warning, str) for warning in content["warnings"]):
        raise ProbeFailure("Parent warnings contain non-text diagnostics")
    policy = content.get("availability")
    if policy not in {"prefer_available", "available_only", "all"}:
        raise ProbeFailure("Parent availability policy is missing")
    children = {child_id: _child_payload(load_child(child_id)) for child_id in checked_ids}
    names = [item["domain_ascii"] for item in children.values()]
    if len(names) != len(set(names)):
        raise ProbeFailure("Checked pool contains duplicate canonical domains")
    states = {child_id: item["availability"] for child_id, item in children.items()}
    counts = {state: sum(value == state for value in states.values())
              for state in ("available", "unavailable", "unknown")}
    for state, field in (("available", "available_count"), ("unavailable", "unavailable_count"),
                         ("unknown", "unknown_count")):
        if _integer(content.get(field), field, 0, 40) != counts[state]:
            raise ProbeFailure(f"Parent {field} does not match checked child evidence")
    selected_states = [states[child_id] for child_id in selected_ids]
    if "unknown" in selected_states or (policy == "available_only" and "unavailable" in selected_states):
        raise ProbeFailure("Unknown or policy-rejected domains entered selected results")
    if policy == "prefer_available" and selected_states != sorted(selected_states,
                                                                   key=lambda state: state != "available"):
        raise ProbeFailure("Prefer-available selection lost available-first order")
    for item in children.values():
        if item.get("country") != content.get("country") or item.get("currency") != content.get("currency"):
            raise ProbeFailure("Child quote context differs from parent")
    quote = content.get("preview_starting_registration")
    if quote is not None:
        if not isinstance(quote, dict) or quote.get("unit") != "year" or quote.get("duration") != 1:
            raise ProbeFailure("Parent preview starting quote lost comparable term context")
        if quote.get("currency") != content.get("currency") or quote.get("tax_basis") not in {"including", "excluding"}:
            raise ProbeFailure("Parent preview starting quote lost tax context")
        amount = quote.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ProbeFailure("Parent preview starting quote has an invalid amount")
    return {
        "parent_embed_id": parent.get("embedId"),
        "query": content.get("query"),
        "checked_embed_ids": checked_ids,
        "selected_embed_ids": selected_ids,
        "checked_count": len(checked_ids),
        "selected_count": len(selected_ids),
        "availability_counts": counts,
        "checked": [{"embed_id": child_id, "domain_ascii": children[child_id]["domain_ascii"],
                     "availability": states[child_id]} for child_id in checked_ids],
    }


def _inspect(env: dict[str, str], api_url: str, chat_id: str, revision: str) -> dict[str, Any]:
    saved = _cli(env, api_url, ["chats", "show", chat_id, "--all"], "Saved graph chat inspection")
    messages = saved.get("messages")
    if not isinstance(messages, list):
        raise ProbeFailure("Saved graph chat has no messages")
    embeds: dict[str, dict[str, Any]] = {}
    for embed_id in _embed_ids([item for item in messages if isinstance(item, dict)]):
        embeds[embed_id] = _cli(env, api_url, ["embeds", "show", embed_id], "Saved parent inspection")
    parents = [embed for embed in embeds.values()
               if embed.get("appId") == "hosting" and embed.get("skillId") == "search_domains"
               and embed.get("type") == "app_skill_use"]
    if not parents:
        raise ProbeFailure("Natural chat has no saved Hosting search parent")
    child_cache: dict[str, dict[str, Any]] = {}
    def load_child(child_id: str) -> dict[str, Any]:
        if child_id not in child_cache:
            child_cache[child_id] = _cli(env, api_url, ["embeds", "show", child_id], "Saved domain inspection")
        return child_cache[child_id]
    groups = [_validate_parent(parent, load_child) for parent in parents]
    if not child_cache:
        raise ProbeFailure("Natural chat did not save any checked Hosting domain children")
    return {"revision": revision, "chat_id": chat_id, "chat_private": True,
            "parent_count": len(groups), "child_count": len(child_cache), "groups": groups}


def _sdk_embeds(env: dict[str, str], api_url: str, chat_id: str, access: str,
                target_ids: list[str], key_id: str) -> dict[str, dict[str, Any]]:
    device_id = f"hosting-graph-{access}"
    if access == "npm":
        program = """import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
const client = new OpenMates({apiUrl: process.env.OPENMATES_API_URL,
  apiKey: process.env.OPENMATES_API_KEY, deviceId: process.env.OPENMATES_GRAPH_DEVICE_ID});
const loaded = await client.chats.load(process.env.OPENMATES_GRAPH_CHAT_ID);
const wanted = new Set(JSON.parse(process.env.OPENMATES_GRAPH_TARGET_IDS));
const embeds = (loaded.embeds || []).filter(item => wanted.has(item.embed_id || item.id));
console.log(JSON.stringify({embeds: embeds.map(item => ({id: item.embed_id || item.id,
  type: item.type, content: item.content}))}));"""
        command = ["node", "--input-type=module", "-e", program]
    elif access == "pip":
        program = """import json, os
from openmates import OpenMates
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'],
                   api_url=os.environ['OPENMATES_API_URL'],
                   device_id=os.environ['OPENMATES_GRAPH_DEVICE_ID'])
loaded = client.chats.load(os.environ['OPENMATES_GRAPH_CHAT_ID'])
wanted = set(json.loads(os.environ['OPENMATES_GRAPH_TARGET_IDS']))
embeds = [item for item in loaded.get('embeds', []) if item.get('embed_id', item.get('id')) in wanted]
print(json.dumps({'embeds': [{'id': item.get('embed_id', item.get('id')),
                            'type': item.get('type'), 'content': item.get('content')}
                           for item in embeds]}))"""
        command = ["python3", "-c", program]
    else:
        raise ProbeFailure("Unsupported SDK graph surface")
    python_path = str(ROOT / "packages/openmates-python")
    if env.get("PYTHONPATH"):
        python_path += os.pathsep + env["PYTHONPATH"]
    sdk_env = {**env, "OPENMATES_GRAPH_DEVICE_ID": device_id,
               "OPENMATES_GRAPH_CHAT_ID": chat_id,
               "OPENMATES_GRAPH_TARGET_IDS": json.dumps(target_ids),
               "PYTHONPATH": python_path}
    result = _run(command, env=sdk_env, label=f"{access} graph load", timeout=180)
    if result.returncode and "403" in result.stderr + result.stdout:
        _approve_sdk_device(env, api_url, key_id, access, device_id)
        result = _run(command, env=sdk_env, label=f"{access} graph load after approval", timeout=180)
    if result.returncode:
        raise ProbeFailure(f"{access} SDK graph load failed (exit {result.returncode})")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeFailure(f"{access} SDK graph load returned invalid JSON") from exc
    rows = payload.get("embeds") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProbeFailure(f"{access} SDK graph load returned no embed list")
    return {item["id"]: item for item in rows
            if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _approve_sdk_device(env: dict[str, str], api_url: str, key_id: str,
                        access: str, device_id: str) -> None:
    program = """import { OpenMatesClient } from './frontend/packages/openmates-cli/dist/index.js';
const client = new OpenMatesClient({apiUrl: process.env.OPENMATES_API_URL});
if (!client.hasSession()) throw new Error('Owner session missing');
const keys = await client.listApiKeys();
if (!(keys.api_keys || []).some(key => key.id === process.env.OPENMATES_GRAPH_KEY_ID))
  throw new Error('Disposable key does not belong to owner');
const current = await client.settingsGet('api-key-devices');
const matches = (current.devices || []).filter(device =>
  device.api_key_id === process.env.OPENMATES_GRAPH_KEY_ID &&
  device.access_type === process.env.OPENMATES_GRAPH_ACCESS &&
  device.machine_identifier === process.env.OPENMATES_GRAPH_DEVICE_ID);
if (matches.length !== 1) throw new Error('Disposable SDK device is not unique');
if (!matches[0].approved_at)
  await client.settingsPost('api-key-devices/' + matches[0].id + '/approve', {});
console.log(JSON.stringify({approved: true}));"""
    owner_env = {key: value for key, value in env.items() if key != "OPENMATES_API_KEY"}
    owner_env.update({"OPENMATES_API_URL": api_url, "OPENMATES_GRAPH_KEY_ID": key_id,
                      "OPENMATES_GRAPH_ACCESS": access, "OPENMATES_GRAPH_DEVICE_ID": device_id})
    result = _run(["node", "--input-type=module", "-e", program], env=owner_env,
                  label=f"{access} disposable device approval", timeout=90)
    if result.returncode:
        raise ProbeFailure(f"{access} disposable device approval failed")


def _verify_sdk_parity(env: dict[str, str], api_url: str, receipt: dict[str, Any], key_id: str) -> None:
    chat_id = receipt["chat_id"]
    targets = list(dict.fromkeys(child_id for group in receipt["groups"]
                                 for child_id in [group["parent_embed_id"], *group["checked_embed_ids"]]))
    # CLI comparisons use the logged-in owner; the disposable API key is only for the two SDK devices.
    owner_env = {name: value for name, value in env.items() if name != "OPENMATES_API_KEY"}
    expected = {embed_id: _cli(owner_env, api_url, ["embeds", "show", embed_id], "CLI graph comparison")
                for embed_id in targets}
    for access in ("npm", "pip"):
        actual = _sdk_embeds(env, api_url, chat_id, access, targets, key_id)
        if set(actual) != set(expected):
            raise ProbeFailure(f"{access} SDK did not retain all checked graph embeds")
        for embed_id in targets:
            if actual[embed_id].get("type") != expected[embed_id].get("type"):
                raise ProbeFailure(f"{access} SDK graph embed type differs from CLI")
            if actual[embed_id].get("content") != expected[embed_id].get("content"):
                raise ProbeFailure(f"{access} SDK graph content differs from CLI")
    receipt["sdk_parity"] = {"npm": "pass", "pip": "pass", "compared_embeds": len(targets)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify saved Hosting parent/child graph on dev")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--chat-receipt", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--require-sdk", action="store_true",
                        help="Compare npm/pip chats.load; may approve their exact disposable test devices")
    parser.add_argument("--sdk-key-env", default="OPENMATES_HOSTING_GRAPH_API_KEY")
    parser.add_argument("--sdk-key-id-env", default="OPENMATES_HOSTING_GRAPH_KEY_ID")
    args = parser.parse_args()
    if urlsplit(args.api_url).scheme != "https" or urlsplit(args.api_url).hostname != "api.dev.openmates.org":
        raise ProbeFailure("Graph verification only runs against the dev API")
    if not CLI_DIST.is_file():
        raise ProbeFailure("Built local CLI is required")
    prior = json.loads(args.chat_receipt.read_text(encoding="utf-8"))
    chat_id = prior.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id:
        raise ProbeFailure("Private chat receipt has no chat ID")
    with tempfile.TemporaryDirectory(prefix="hosting-graph-") as state_dir:
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("OPENMATES_TEST_ACCOUNT") and name != "OPENMATES_API_KEY"}
        env.update(_test_account_env(args.env_file))
        env.update({"OPENMATES_STATE_DIR": state_dir, "OPENMATES_PROFILE": "",
                    "OPENMATES_API_URL": args.api_url, "PLAYWRIGHT_WORKER_SLOT": ""})
        login = _run(["node", str(LOGIN_HELPER), "login", "--api-url", args.api_url],
                     env=env, label="Graph test-account login", timeout=180)
        if login.returncode:
            raise ProbeFailure("Graph test-account login failed")
        receipt = _inspect(env, args.api_url, chat_id, args.revision)
        if args.require_sdk:
            api_key = os.environ.get(args.sdk_key_env)
            key_id = os.environ.get(args.sdk_key_id_env)
            if not api_key or not key_id:
                raise ProbeFailure("SDK parity needs a disposable API key and key ID in private environment")
            env["OPENMATES_API_KEY"] = api_key
            _verify_sdk_parity(env, args.api_url, receipt, key_id)
            env.pop("OPENMATES_API_KEY", None)
        else:
            receipt["sdk_parity"] = "not_run"
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.chmod(0o600)
    print(f"PASS hosting embed graph; parents={receipt['parent_count']} children={receipt['child_count']} sdk={receipt['sdk_parity'] != 'not_run'} revision={args.revision}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        raise SystemExit(f"FAIL: {exc}") from None
