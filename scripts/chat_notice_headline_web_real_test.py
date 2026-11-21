# contract-test-file: infrastructure
"""Opt-in dev-only real-inference proof that the background chat notice shows the summary headline (TASK-390).

Runs frontend/apps/web_app/tests/chat-notice-headline-real.spec.ts without mocks
against https://app.dev.openmates.org on a phone viewport: a code-heavy request
is answered by @Gemini-3.8-Flash while another new chat is open, and the in-app
notice of the background chat must read "<icon> <summary>" with the chat title
and the mate image, never "New AI response ready". Same harness, leases and
throwaway-account fallback as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/chat_notice_headline_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/chat-notice-headline/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. The spec deletes its chat.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/chat-notice-headline-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Chat notice headline", doc=__doc__))
