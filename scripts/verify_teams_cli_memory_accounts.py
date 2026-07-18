#!/usr/bin/env python3
"""Real OpenMates CLI Teams memory/account verification entrypoint.

This gate fails until real CLI memory and connected-account commands prove strict
personal/team isolation, viewer write denial, and removed-member cleanup against
a deployed API.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("memory-accounts"))
