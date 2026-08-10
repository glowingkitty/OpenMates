#!/usr/bin/env python3
"""Real OpenMates CLI Teams data portability verification entrypoint.

Exports a test team, verifies the artifact is team-scoped, marks it as rewrapped
for a destination team, and imports it through the compiled CLI. The script is
safe to rerun and cleans up test teams best-effort.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("data-portability"))
