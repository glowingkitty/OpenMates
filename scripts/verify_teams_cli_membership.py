#!/usr/bin/env python3
"""Real OpenMates CLI Teams membership verification entrypoint.

Exercises invite, accept, access-request listing, and owner/admin approval against
a real API. The flow verifies the V1 access-approval contract without exposing
raw team keys in email or accept requests.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("membership"))
