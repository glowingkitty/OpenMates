#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for travel connection results (TASK-3927).

Runs frontend/apps/web_app/tests/travel-results-real.spec.ts without mocks
against https://app.dev.openmates.org on a phone and a laptop viewport:
@Gemini-3.8-Flash searches train connections, every connection card in the
answer opens a complete fullscreen with its route map and readable times, and
the results calendar keeps its day headers and hour column while scrolling.
Same harness, leases and throwaway-account fallback as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/travel_results_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/travel-results/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. The spec deletes its chat.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/travel-results-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Travel connection results", doc=__doc__))
