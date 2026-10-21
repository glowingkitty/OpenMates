#!/usr/bin/env python3
# contract-test-file: tooling
"""Probe the real, free CCC caption API without OpenMates or AI inference."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.shared.providers.media_ccc import MediaCCCClient, MediaCCCError

__test__ = False
CAPTIONED = "https://media.ccc.de/v/39c3-a-post-american-enshittification-resistant-internet"
NO_CAPTIONS = "https://media.ccc.de/v/37c3-other-59123-from-hacker-to-furry"
SRT = "https://media.ccc.de/v/36c3-10652-bahnmining_-_punktlichkeit_ist_eine_zier"


async def probe(name):
    started = time.monotonic()
    try:
        url = {"vtt": CAPTIONED, "srt": SRT, "no_captions": NO_CAPTIONS}[name]
        try:
            transcript = await MediaCCCClient().fetch_transcript(url)
        except MediaCCCError as exc:
            if name == "no_captions" and "No published captions" in str(exc):
                return {"status": "pass", "duration": time.monotonic() - started, "outcome": "no_published_captions"}
            raise
        if name == "no_captions" or not transcript.captions:
            raise AssertionError("Unexpected caption availability")
        return {"status": "pass", "duration": time.monotonic() - started, "language": transcript.language,
                "segments": len(transcript.captions), "words": sum(len(c.text.split()) for c in transcript.captions)}
    except Exception as exc:
        return {"status": "fail", "duration": time.monotonic() - started, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", choices=["vtt", "srt", "no_captions"])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--api-key", help="Not needed: this provider is public and unauthenticated.")
    args = parser.parse_args()
    if args.list:
        print("vtt: English WebVTT captions\nsrt: German SRT captions\nno_captions: explicit unavailable result")
        return
    names = [args.test] if args.test else ["vtt", "srt", "no_captions"]
    results = {name: asyncio.run(probe(name)) for name in names}
    print(json.dumps(results, indent=2))
    raise SystemExit(any(result["status"] != "pass" for result in results.values()))


if __name__ == "__main__":
    main()
