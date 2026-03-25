#!/usr/bin/env python3
"""
scripts/ci/get_spec_batch.py

Splits Playwright spec files into batches for GitHub Actions matrix jobs.

Given a batch index (0-based) and batch size, discovers all *.spec.ts files
in frontend/apps/web_app/tests/, sorts them alphabetically for deterministic
assignment, and outputs the specs for the requested batch.

Usage:
    python3 scripts/ci/get_spec_batch.py <batch_index> <batch_size>

    # Example: Get specs for batch 0 with batch size 18
    python3 scripts/ci/get_spec_batch.py 0 18

Output:
    Writes SPECS_FOR_BATCH to GITHUB_OUTPUT (for GitHub Actions) and also
    prints to stdout (for local testing). The value is a space-separated
    list of spec filenames.

    Also outputs TOTAL_BATCHES so the matrix strategy can be computed
    dynamically.
"""

import glob
import math
import os
import sys


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <batch_index> <batch_size>", file=sys.stderr)
        sys.exit(1)

    batch_index = int(sys.argv[1])
    batch_size = int(sys.argv[2])

    # Discover spec files
    project_root = os.environ.get(
        "PROJECT_ROOT",
        os.path.join(os.path.dirname(__file__), "..", ".."),
    )
    spec_dir = os.path.join(project_root, "frontend", "apps", "web_app", "tests")
    spec_files = sorted(glob.glob(os.path.join(spec_dir, "*.spec.ts")))

    if not spec_files:
        print("No spec files found", file=sys.stderr)
        # Still set output so the job doesn't fail
        _set_output("SPECS_FOR_BATCH", "")
        _set_output("TOTAL_BATCHES", "0")
        sys.exit(0)

    # Extract basenames
    basenames = [os.path.basename(f) for f in spec_files]

    # Compute batch
    total_batches = math.ceil(len(basenames) / batch_size)
    _set_output("TOTAL_BATCHES", str(total_batches))

    start = batch_index * batch_size
    end = min(start + batch_size, len(basenames))

    if start >= len(basenames):
        # This batch has no specs (matrix is larger than needed)
        _set_output("SPECS_FOR_BATCH", "")
        print(f"Batch {batch_index}: no specs (total={len(basenames)}, batches={total_batches})")
        sys.exit(0)

    batch_specs = basenames[start:end]
    specs_str = " ".join(batch_specs)

    _set_output("SPECS_FOR_BATCH", specs_str)
    print(f"Batch {batch_index}: {len(batch_specs)} specs (of {len(basenames)} total, {total_batches} batches)")
    print(f"  {specs_str}")


def _set_output(name: str, value: str) -> None:
    """Write to GITHUB_OUTPUT if available (GitHub Actions), else print."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{name}={value}\n")
    # Always print for visibility
    print(f"::set-output name={name}::{value}" if not github_output else f"{name}={value}")


if __name__ == "__main__":
    main()
