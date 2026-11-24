# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for conference questions (TASK-2134).

Runs frontend/apps/web_app/tests/real-inference-events-question.spec.ts without mocks
against https://app.dev.openmates.org: @Gemini-3.8-Flash is asked for the
largest open source conference in Europe and when it happens, the answer carries
an Events app search card that opens its fullscreen, and a chat header image
bubble opens without "Embed not found". Same harness, leases and throwaway-account
fallback as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/events_question_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/events-question/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Use --grep "dictated conference discovery" to record the exact dictated prompt.
Runs against dev, including on E2B. The spec deletes its chat.
"""
from __future__ import annotations

import os
import sys

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-events-question.spec.ts"

if __name__ == "__main__":
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    sys.exit(main(spec=SPEC, title="Events conference question", doc=__doc__, grep_option=True))
