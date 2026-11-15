#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of Flow 2 driven from the web app.

Runs frontend/apps/web_app/tests/agentic-remote-project-web-real.spec.ts without mocks against
https://app.dev.openmates.org with the personal dev test account: in an existing Project whose files
live in a folder on a connected machine, one chat writes a Specification with Checks, a Plan, code and
unit tests into the machine folder, runs the tests there, shows the preview and commits; then the
Project views (Specifications, Checks, files, Timeline) are shown at laptop and phone size.
The remote-access host serving the Project folder must be running and connected.
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/agentic_remote_project_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/agentic-remote-project-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/agentic-remote-project-web-real.spec.ts"

if __name__ == "__main__":
    # Passed into the E2B sandbox (OPENMATES_PROOF_* prefix); there CI=1 is set for tooling, so the
    # spec's CI guard accepts this marker, which only this dev harness sets.
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Flow 2 web", doc=__doc__))
