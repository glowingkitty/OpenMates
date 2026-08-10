#!/usr/bin/env python3
"""Real OpenMates CLI Teams billing verification entrypoint.

Checks a newly-created team has readable billing metadata and can receive a small
test credit event through the compiled CLI. It is intentionally separate from the
team chat AI spend gate.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("billing"))
