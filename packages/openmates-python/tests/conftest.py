"""Python SDK test configuration.

Purpose: make the local package importable without editable installation.
Architecture: package-local tests for packages/openmates-python.
Scope: test-only path setup; production package metadata stays in pyproject.toml.
"""

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
