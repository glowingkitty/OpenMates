#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for live progress of search skills in chat.

Runs frontend/apps/web_app/tests/skill-search-live-progress-chat.spec.ts against
https://app.dev.openmates.org with the personal dev test account, the installed
Chromium and video on: an event discovery request and a product search request
show the live status line (sources done, results so far) and then their results.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/skill_search_progress_web_real_test.py --session ID --revision FULL_SHA \
    --output-dir /tmp/skill-search-progress-proof/run-1 \
    --personal-dev-test-account --allow-paid-dev-inference [--grep "event discovery"]

Never run in CI. The spec deletes its own chats, also on failure.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/skill-search-live-progress-chat.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Search skill live progress", doc=__doc__, grep_option=True))
