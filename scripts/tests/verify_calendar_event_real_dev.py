# contract-test-file: direct surface=cli assertions=calendar-event.assistant.relevant-research,calendar-event.streaming.saved-lifecycle,calendar-event.content.validated,calendar-event.privacy.explicit-local-export
"""Verify a real saved calendar-event answer on dev using isolated CLI state.

Run after generating the answer through the actual OpenMates CLI with default
automatic routing. This never mocks OpenMates, supplies model overrides, copies
credentials, or writes to a calendar. Keep the retained chat private.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chat", help="Exact synthetic test chat ID")
    parser.add_argument("--cli", default="openmates", help="Installed CLI executable")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    state = os.environ.get("OPENMATES_STATE_DIR")
    if not state or not Path(state).is_absolute():
        raise SystemExit("An isolated absolute OPENMATES_STATE_DIR is required")

    def cli(*parts):
        result = subprocess.run(
            [args.cli, "--api-url", "https://api.dev.openmates.org", *parts, "--json"],
            check=True, capture_output=True, text=True, timeout=180,
        )
        return json.loads(result.stdout)

    saved = cli("chats", "show", args.chat, "--all")
    messages = saved["messages"]
    assistants = [m for m in messages if m["role"] == "assistant"]
    assert assistants, "A real completed assistant answer is required"
    ids = {embed for message in messages for embed in message.get("embedIds", [])}
    embeds = [cli("embeds", "show", embed, "--chat", args.chat) for embed in ids]
    events = [e for e in embeds if e.get("type") in {"calendar_event", "calendar-event"}]
    assert len(events) == 1, "One standalone event must survive the saved-chat read"
    embed = events[0]
    content = embed.get("content", {})
    primary = content["primary_event"]
    assert content["status"] == "finished"
    assert content["validation"]["status"] in {"valid", "partial"}
    assert "fosdem" in primary["title"].lower()
    assert primary["start"] == "2027-01-30" and primary["end"] == "2027-02-01"
    assert primary.get("source_url", "").startswith("https://fosdem.org/")
    assert isinstance(content.get("context_events", []), list)
    assert not any("```openmates_calendar_event" in m["content"] for m in assistants)
    assert not any(e.get("content", {}).get("app_id") == "calendar"
                   and e.get("content", {}).get("skill_id") in {"create-event", "update-event", "delete-event"}
                   for e in embeds), "Content creation must not mutate a connected calendar"
    reloaded = cli("embeds", "show", embed["embedId"], "--chat", args.chat)
    assert reloaded["content"]["primary_event"] == primary
    receipt = {
        "passed": True, "chat_id": args.chat, "embed_id": embed["embedId"],
        "title": primary["title"], "start": primary["start"], "exclusive_end": primary["end"],
        "source": primary["source_url"], "context_count": len(content.get("context_events", [])),
        "cloud_mutations": 0, "reloaded_same_event": True,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    args.receipt.chmod(0o600)
    print(f"Verified {primary['title']}: January 30–31, 2027; one saved event; no calendar write.")


if __name__ == "__main__":
    main()
