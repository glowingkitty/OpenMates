# scripts/cli_code_run_real_test.py
# contract-test-file: infrastructure
"""Opt-in dev-only real proof: the native CLI runs a Python project on E2B.

Runs frontend/apps/web_app/tests/cli-native-code-run-real.spec.ts against
https://app.dev.openmates.org: `openmates apps code run --dir <recipe scaler>
--entry main.py` is recorded in a real terminal and must print the program's
real E2B output. No AI inference. Same harness, leases and receipt as
scripts/agentic_app_real_test.py (personal dev account when free).

Example (after deployment and `python3 scripts/heavy_slot.py run -- cargo build -p openmates`):
  python3 scripts/cli_code_run_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/cli-code-run-proof/run-1 --personal-dev-test-account

Never run in CI.
"""
from __future__ import annotations

import os
from pathlib import Path

from agentic_app_real_test import CLI_BINARY, require_fresh_cli
from design_embroidery_web_real_test import installed_chromium, main

SPEC = "tests/cli-native-code-run-real.spec.ts"

if __name__ == "__main__":
    if not Path(CLI_BINARY).is_file():
        raise SystemExit(f"native CLI missing: build it first ({CLI_BINARY})")
    require_fresh_cli()
    os.environ.update(PW_CHROMIUM=str(installed_chromium()), OPENMATES_NATIVE_CLI=str(CLI_BINARY),
                      OPENMATES_HEAVY_REMOTE="0")
    raise SystemExit(main(spec=SPEC, title="CLI code run (E2B)", doc=__doc__))
