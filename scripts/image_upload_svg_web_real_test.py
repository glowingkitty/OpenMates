# contract-test-file: infrastructure
"""Opt-in dev-only real-inference phone proof for upload + SVG generate (TASK-2115).

Runs frontend/apps/web_app/tests/image-upload-svg-generate-real.spec.ts without
mocks against https://app.dev.openmates.org: a photo is uploaded in a new chat,
@Gemini-3.8-Flash is asked for an SVG based on it, and the turn must complete
with the View card showing the photo and the Generate card finished, in call
order. Same harness, leases and throwaway-account fallback as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/image_upload_svg_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/image-upload-svg/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. The spec deletes its chat.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/image-upload-svg-generate-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Image upload SVG generate", doc=__doc__))
