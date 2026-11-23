#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of the cloud agentic coding flow driven from the web app.

Runs frontend/apps/web_app/tests/agentic-cloud-project-web-real.spec.ts without mocks against
https://app.dev.openmates.org with the personal dev test account: the web app sends every prompt
(recipe app into a hosted Project, install and build commands, recorded browser test with commit),
shows the preview, Project files and Timeline at laptop and phone size, then asks in a new chat of
the Project for a Specification with Checks and a Plan. The CLI is not used.
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/agentic_cloud_project_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/agentic-cloud-project-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/agentic-cloud-project-web-real.spec.ts"

if __name__ == "__main__":
    # Passed into the E2B sandbox (OPENMATES_PROOF_* prefix); the spec's CI guard accepts this marker.
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Cloud Project web", doc=__doc__))
