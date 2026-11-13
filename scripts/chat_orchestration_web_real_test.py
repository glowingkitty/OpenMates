#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof that any chat starts and coordinates other main chats.

Runs frontend/apps/web_app/tests/chat-orchestration-main-chats.spec.ts against
https://app.dev.openmates.org with the personal dev test account, the installed
Chromium and video on: a chat starts a spawned main chat, its "Started chat"
event opens that chat (brief as first message, link back to the creator), and
the creator then shows the spawned chat's report or finished event.
Plan: docs/plans/chat-orchestration-main-chats/plan.yml (T-E2E).

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/chat_orchestration_web_real_test.py --session ID --revision FULL_SHA \
    --output-dir /tmp/chat-orchestration-proof/run-1 \
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. The spec deletes the creator and the spawned chat.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/chat-orchestration-main-chats.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Chat orchestration of main chats", doc=__doc__))
