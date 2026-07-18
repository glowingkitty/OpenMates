#!/usr/bin/env python3
"""Real OpenMates CLI Teams lifecycle verification entrypoint.

Runs create/list/switch/show/delete against the configured API using the compiled
CLI and the repository test-account login helper. This script is referenced by
docs/specs/teams-v1/spec.yml as the CLI-first Teams lifecycle gate.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("lifecycle"))
