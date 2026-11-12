# backend/shared/providers/e2b_test_recorder.py
#
# Host side of the browser test recorder (contract: docs/plans/agentic-tests-and-git-sync/
# contracts/test-run.md). browser_recorder_wrapper() is the `recorder_wrapper`
# for run_tests_in_e2b: it returns an argv that unpacks the recorder assets in
# test_recorder_assets/ into the sandbox at run time and runs the user's
# command through them, so no E2B template rebuild is needed.

from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

from backend.shared.providers.e2b_application_preview import APPLICATION_CAPTURE_DIRECTORY
from backend.shared.providers.e2b_code_runner import WORKSPACE_DIR
from backend.shared.python_schemas.code_test_run import TestRunSpec

ASSET_DIR = Path(__file__).parent / "test_recorder_assets"
SANDBOX_ASSET_DIR = "/tmp/openmates-recorder"
RECORDER_SCRIPT = "record_browser.py"
ASSET_FILES = (RECORDER_SCRIPT, "reporter.cjs")

# Runs inside the sandbox: unpack assets (argv[1]), then execute the recorder.
_BOOTSTRAP = (
    "import sys,os,json,zlib,base64,runpy;"
    f"d=json.loads(zlib.decompress(base64.b64decode(sys.argv[1])));os.makedirs('{SANDBOX_ASSET_DIR}',exist_ok=True);"
    f"[open('{SANDBOX_ASSET_DIR}/'+n,'w').write(t) for n,t in d.items()];"
    f"sys.argv=['{RECORDER_SCRIPT}']+sys.argv[2:];"
    f"runpy.run_path('{SANDBOX_ASSET_DIR}/{RECORDER_SCRIPT}',run_name='__main__')"
)


def recorder_payload() -> str:
    """Compressed, base64 bundle of the recorder assets."""
    bundle = {name: (ASSET_DIR / name).read_text() for name in ASSET_FILES}
    return base64.b64encode(zlib.compress(json.dumps(bundle).encode(), 9)).decode()


def browser_recorder_wrapper(spec: TestRunSpec) -> list[str]:
    """argv replacing spec.test_command.argv for kind == "browser"."""
    args = ["--workspace-root", WORKSPACE_DIR, "--capture-dir", APPLICATION_CAPTURE_DIRECTORY]
    if spec.preview_step:
        args += ["--preview-step", spec.preview_step]
    return ["python3", "-c", _BOOTSTRAP, recorder_payload(), *args, "--", *spec.test_command.argv]
