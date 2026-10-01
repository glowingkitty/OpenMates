#!/usr/bin/env python3
# contract-test-file: tooling
"""Dev-only real CLI chat proof for Hosting domain search and social app naming.

Run only after programmatic Hosting CI and dev deployment. The disposable test
account chat stays private; this script never shares or publishes it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import urlsplit

from test_hosting_requirements import (
    CLI_DIST, DEFAULT_API_URL, LOGIN_HELPER, ProbeFailure,
    _run, _test_account_env,
)


PROMPT = (
    "Recommend good product names for a social app that is a social hub to stay "
    "in contact with people I met in person and to meet new people. Please check "
    "whether multiple candidate names have domains available across .com, .net, "
    "and .app, and give me a shortlist that considers the checked domain availability, "
    "renewal prices, and any premium or registration restrictions. Only describe "
    "availability that was actually checked."
)
FOLLOWUP_PROMPT = (
    "Please continue this name search. The five base names you checked are in use, "
    "so propose a few more distinctive names for this in-person social hub and actually "
    "check their .com, .net, and .app availability. Also look at any suitable available "
    "alternatives already returned by your previous Hosting search. Recommend concrete, "
    "fully qualified domains only when availability was checked, and compare evidenced "
    "registration and renewal prices and relevant restrictions. Do not guess about unchecked names."
)
RECOVERY_PROMPT = (
    "Please finish the name recommendation for this in-person social hub. Give me 2–4 useful "
    "product names with concrete domain options confirmed available by your earlier checks, "
    "and include the renewal price and restrictions where the checked results provide them. "
    "Use the domain results already checked in this chat where possible; refresh only if needed. "
    "Clearly separate checked available options from names or domains that remain unverified."
)
DOMAIN_RE = re.compile(r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)+(?:com|net|app)\b", re.I)
EMBED_REF_RE = re.compile(r"embed:([A-Za-z0-9_.:-]+)")
INLINE_EMBED_RE = re.compile(r'"embed_id"\s*:\s*"([A-Za-z0-9_.:-]+)"')


def _cli(env: dict[str, str], api_url: str, args: list[str], stage: str, *, timeout: int = 240) -> dict[str, Any]:
    result = _run(["node", str(CLI_DIST), "--api-url", api_url, *args, "--json"],
                  env=env, label=stage, timeout=timeout)
    if result.returncode != 0:
        raise ProbeFailure(f"{stage} failed (exit {result.returncode}); private output withheld")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeFailure(f"{stage} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProbeFailure(f"{stage} returned an invalid object")
    return value


def _embed_ids(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        for field in ("embedIds", "embed_ids"):
            value = message.get(field)
            if isinstance(value, list):
                found.update(item for item in value if isinstance(item, str) and item)
        content = message.get("content")
        if isinstance(content, str):
            found.update(EMBED_REF_RE.findall(content))
            found.update(INLINE_EMBED_RE.findall(content))
    return found


def _child_ids(content: dict[str, Any]) -> set[str]:
    value = content.get("embed_ids")
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str) and item}
    if isinstance(value, str):
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                return {item for item in decoded if isinstance(item, str) and item}
        return {item.strip() for item in value.split("|") if item.strip()}
    return set()


def _group_details(content: dict[str, Any]) -> tuple[set[str], set[str]]:
    queries: set[str] = set()
    domains: set[str] = set()
    query = content.get("query")
    if isinstance(query, str) and query.strip():
        queries.add(query.strip())
    for field in ("requests", "results", "checked_results"):
        value = content.get(field)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            query = item.get("query")
            if isinstance(query, str) and query.strip():
                queries.add(query.strip())
            name = item.get("domain_ascii")
            if isinstance(name, str) and name.strip():
                domains.add(name.strip().lower())
            for inner_field in ("results", "checked_results"):
                inner = item.get(inner_field)
                if isinstance(inner, list):
                    domains.update(child["domain_ascii"].lower() for child in inner
                                   if isinstance(child, dict) and isinstance(child.get("domain_ascii"), str))
    return queries, domains


def _domain_statuses(content: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            name, availability = item.get("domain_ascii"), item.get("availability")
            if isinstance(name, str) and availability in {"available", "unavailable", "unknown"}:
                statuses[name.lower()] = availability
            for field in ("results", "checked_results"):
                visit(item.get(field))
    visit(content)
    return statuses


def _verify_chat(env: dict[str, str], api_url: str, chat_id: str, revision: str) -> dict[str, Any]:
    saved = _cli(env, api_url, ["chats", "show", chat_id, "--all"], "Saved chat inspection")
    messages = saved.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ProbeFailure("Saved chat has no inspectable messages")
    assistant_messages = [message for message in messages
                          if isinstance(message, dict) and message.get("role") == "assistant"
                          and isinstance(message.get("content"), str)]
    if not assistant_messages:
        raise ProbeFailure("Saved chat has no final assistant recommendation")
    final_text = assistant_messages[-1]["content"].strip()
    if len(final_text) < 80:
        raise ProbeFailure("Final recommendation is incomplete")

    pending = _embed_ids([item for item in messages if isinstance(item, dict)])
    seen: set[str] = set()
    parent_child_ids: set[str] = set()
    hosting_parents = 0
    queries: set[str] = set()
    checked_domains: set[str] = set()
    domain_statuses: dict[str, str] = {}
    while pending and len(seen) < 100:
        embed_id = pending.pop()
        if embed_id in seen:
            continue
        seen.add(embed_id)
        try:
            embed = _cli(env, api_url, ["embeds", "show", embed_id], "Saved embed inspection", timeout=90)
        except ProbeFailure:
            continue
        content = embed.get("content")
        if not isinstance(content, dict):
            continue
        if embed.get("appId") != "hosting" or embed.get("skillId") != "search_domains":
            continue
        if embed.get("type") not in {"app_skill_use", "app-skill-use"}:
            continue
        hosting_parents += 1
        parent_queries, parent_domains = _group_details(content)
        queries.update(parent_queries)
        checked_domains.update(parent_domains)
        domain_statuses.update(_domain_statuses(content))
        name = content.get("domain_ascii")
        if isinstance(name, str):
            checked_domains.add(name.lower())
        parent_child_ids.update(_child_ids(content))
    if hosting_parents < 1:
        raise ProbeFailure("Natural chat did not produce a saved hosting.search_domains parent embed")
    for child_id in sorted(parent_child_ids - seen)[:100]:
        try:
            child = _cli(env, api_url, ["embeds", "show", child_id], "Saved domain inspection", timeout=90)
        except ProbeFailure:
            continue
        if child.get("appId") != "hosting":
            continue
        child_content = child.get("content")
        if not isinstance(child_content, dict):
            continue
        name = child_content.get("domain_ascii")
        if isinstance(name, str) and name.strip():
            checked_domains.add(name.strip().lower())
        child_queries, child_domains = _group_details(child_content)
        queries.update(child_queries)
        checked_domains.update(child_domains)
        domain_statuses.update(_domain_statuses(child_content))
    if len(queries) < 2 and len(checked_domains) < 2:
        raise ProbeFailure("Hosting embed evidence did not identify multiple domain searches")
    recommendation_text = re.sub(r"\]\([^)]+\)", "]", final_text)
    mentioned = sorted({domain.lower() for domain in DOMAIN_RE.findall(recommendation_text)
                        if not domain.split(".")[0].isdigit()})
    if len(mentioned) < 2:
        raise ProbeFailure("Final answer did not recommend multiple concrete domains")
    if checked_domains and len(set(mentioned) & checked_domains) < 2:
        raise ProbeFailure("Final recommendations did not match multiple checked domains")
    available_recommendations = sorted(domain for domain in mentioned
                                       if domain_statuses.get(domain) == "available")
    if len(available_recommendations) < 2:
        raise ProbeFailure("Final answer did not recommend two confirmed available domains")
    return {
        "revision": revision,
        "skill": "hosting.search_domains",
        "chat_id": chat_id,
        "chat_private": True,
        "hosting_parent_embeds": hosting_parents,
        "search_queries": sorted(queries),
        "checked_domains": sorted(checked_domains),
        "checked_domain_statuses": domain_statuses,
        "recommended_domains": mentioned,
        "available_recommendations": available_recommendations,
        "final_recommendations": final_text[:12000],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove natural Hosting skill selection in a private real dev CLI chat")
    parser.add_argument("--env-file", required=True, type=Path, help="Canonical test-account .env")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--revision", required=True, help="Deployed dev revision")
    parser.add_argument("--output", required=True, type=Path, help="Private JSON receipt path")
    parser.add_argument("--existing-chat-file", type=Path,
                        help="Private prior receipt; send one natural follow-up in the same chat")
    parser.add_argument("--recovery", action="store_true",
                        help="Ask for final recommendations from already-checked domain results")
    args = parser.parse_args()
    if args.recovery and not args.existing_chat_file:
        raise ProbeFailure("Recovery requires an existing private chat receipt")
    if urlsplit(args.api_url).scheme != "https" or urlsplit(args.api_url).hostname != "api.dev.openmates.org":
        raise ProbeFailure("This chat probe only runs against the dev API")
    if not CLI_DIST.is_file():
        raise ProbeFailure("Built local CLI is required")
    account_env = _test_account_env(args.env_file)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hosting-social-chat-") as state_dir:
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("OPENMATES_TEST_ACCOUNT") and name != "OPENMATES_API_KEY"}
        env.update(account_env)
        env.update({"OPENMATES_STATE_DIR": state_dir, "OPENMATES_PROFILE": "",
                    "OPENMATES_API_URL": args.api_url, "PLAYWRIGHT_WORKER_SLOT": ""})
        login = _run(["node", str(LOGIN_HELPER), "login", "--api-url", args.api_url],
                     env=env, label="Test-account login", timeout=180)
        if login.returncode != 0:
            raise ProbeFailure(f"Test-account login failed (exit {login.returncode})")
        if args.existing_chat_file:
            prior = json.loads(args.existing_chat_file.read_text(encoding="utf-8"))
            existing_id = prior.get("chat_id")
            if not isinstance(existing_id, str) or not existing_id:
                raise ProbeFailure("Prior private receipt has no chat ID")
            followup_prompt = RECOVERY_PROMPT if args.recovery else FOLLOWUP_PROMPT
            created = _cli(env, args.api_url, ["chats", "send", "--chat", existing_id, followup_prompt],
                           "Natural social-app follow-up", timeout=600)
        else:
            created = _cli(env, args.api_url, ["chats", "new", PROMPT], "Natural social-app chat", timeout=600)
        chat_id = created.get("chat_id") or created.get("chatId") or created.get("id")
        if not isinstance(chat_id, str) or not chat_id:
            raise ProbeFailure("CLI chat creation returned no chat ID")
        output.write_text(json.dumps({"revision": args.revision, "chat_id": chat_id,
                                      "chat_private": True, "status": "pending_inspection"}) + "\n", encoding="utf-8")
        output.chmod(0o600)
        receipt = _verify_chat(env, args.api_url, chat_id, args.revision)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.chmod(0o600)
    print(f"PASS hosting social chat; parent_embeds={receipt['hosting_parent_embeds']} recommended_domains={len(receipt['recommended_domains'])} revision={args.revision}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        raise SystemExit(f"FAIL: {exc}") from None
