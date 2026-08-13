#!/usr/bin/env python3
"""Run the real OpenMates CLI Teams profile-image verifier.

This wrapper exercises generated profile metadata, uploaded team image storage,
and authenticated profile-image retrieval against a real API. It delegates the
session setup and cleanup mechanics to verify_teams_cli_common.py.
"""

from verify_teams_cli_common import main


if __name__ == "__main__":
    raise SystemExit(main("profile-images"))
