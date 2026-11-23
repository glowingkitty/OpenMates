#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of layered focuses in a Project chat.

Runs frontend/apps/web_app/tests/real-inference-project-layered-focus.spec.ts without mocks against
https://app.dev.openmates.org: a new feature request layers Write specification over the
Project focus, ending that layer keeps the Project focus, and a Focus stored in the Project
layers the same way. Screenshots, the Playwright video, the run log and a receipt land in
--output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/project_layered_focus_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/layered-focus-web-proof/run-1 \\
    --personal-dev-test-account --throwaway-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-project-layered-focus.spec.ts"

if __name__ == "__main__":
    # Passed into the E2B sandbox (OPENMATES_PROOF_* prefix); there CI=1 is set for tooling, so the
    # spec's CI guard accepts this marker, which only this dev harness sets.
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Layered focus in a Project (web)", doc=__doc__))
