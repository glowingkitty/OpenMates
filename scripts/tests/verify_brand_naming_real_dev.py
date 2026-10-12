# contract-test-file: direct surface=cli assertions=brand-naming.activation,brand-naming.flow,trademarks.evidence,trademarks.parity
"""Verify a retained real naming conversation; run only on dev with isolated CLI state.

Create the conversation through the real CLI first, starting with the exact user
phrase below. This reads its live messages and embeds, never supplies AI replay.
"""
import argparse
import json
import os
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chat")
    parser.add_argument("--finalists", nargs=2, required=True)
    parser.add_argument("--cli-js", help="Exact built CLI path, or use the global CLI")
    args = parser.parse_args()
    assert os.environ.get("OPENMATES_STATE_DIR"), "Isolated CLI state is required"
    command = ["node", args.cli_js] if args.cli_js else ["openmates"]

    def cli(*parts):
        result = subprocess.run([*command, "--api-url", "https://api.dev.openmates.org", *parts, "--json"],
                                check=True, capture_output=True, text=True, timeout=120)
        return json.loads(result.stdout)

    chat = cli("chats", "show", args.chat, "--all")
    messages = chat["messages"]
    users = [message for message in messages if message["role"] == "user"]
    assistants = [message for message in messages if message["role"] == "assistant"]
    assert users[0]["content"] == "Help me find a name for my new product."
    assert len(users) >= 3 and len(assistants) >= 3, "Intake, shortlist and research must be real turns"
    intake = assistants[0]["content"]
    assert len(intake.split()) <= 60 and "interactive_question" not in intake
    shortlist = assistants[1]["content"]
    candidates = re.findall(r"(?m)^\s*(?:\d+\.\s+|[-*]\s+(?:\[[ x]\]\s+)?)\*\*[^*]+\*\*", shortlist)
    assert 6 <= len(candidates) <= 8 and "unchecked" in shortlist.lower()
    assert "interactive_question" not in shortlist
    assert not any("```sheet" in message["content"] or "```doc" in message["content"] for message in assistants)

    ids = {embed for message in messages for embed in message.get("embedIds", [])}
    embeds = [cli("embeds", "show", embed) for embed in ids]
    assert not any(embed.get("type") in {"sheet", "sheets-sheet", "doc", "docs-doc"} for embed in embeds), "Keep the comparison inline"
    content = [embed.get("content", {}) for embed in embeds]
    assert any(item.get("focus_id") == "business-find_brand_name" for item in content), "Automatic activation evidence missing"
    searches = [item for item in content if item.get("app_id") == "business" and item.get("skill_id") == "search_trademarks"]
    assert searches, "A real trademark embed is required"
    names = set()
    for saved in searches:
        data = next((item for item in saved.get("results", []) if isinstance(item, dict) and "coverage" in item), saved)
        assert data["success"] is True and data["status"] == "finished"
        regions = data["regions"].split("|") if isinstance(data["regions"], str) else data["regions"]
        assert regions == ["US"]
        assert saved.get("max_results") == 5, "The initial research must stay bounded"
        for row in data["coverage"]:
            assert row["status"] == "searched" and row.get("checked_at")
            assert row["returned_count"] <= 5
            names.add(row["query"])
        assert "legal availability" in data["limitation"]
    assert names == set(args.finalists), "Only selected finalists should be researched"
    apps = {item.get("app_id") for item in content}
    assert {"hosting", "web", "business"} <= apps, "Domain, web and trademark evidence is required"
    print(json.dumps({"passed": True, "user_turns": len(users), "intake_words": len(intake.split()),
                      "shortlist_count": len(candidates), "trademark_names": len(names)}))


if __name__ == "__main__":
    main()
