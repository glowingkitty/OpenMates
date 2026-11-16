#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for mixed routes with an owned pass (TASK-1047).

Runs frontend/apps/web_app/tests/travel-mixed-routes-real.spec.ts without mocks
against https://app.dev.openmates.org: the traveller owns a Deutschland-Ticket and
asks @Gemini-3.8-Flash for Munich to Zurich (phone and laptop), Berlin to Prague
and Berlin to Copenhagen (laptop). Munich to Zurich must offer a composed route
whose fullscreen lists the pass part and the paid part. Same harness, leases and
throwaway-account fallback as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/travel_mixed_routes_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/travel-mixed-routes/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. The spec deletes its chats.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/travel-mixed-routes-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Travel mixed routes", doc=__doc__, grep_option=True))
