"""Container entry point for migration followed by API startup.

Migrations complete before the process accepts requests. Startup fails closed
when the dedicated database is absent or invalid; there is no product database
or local-file fallback.
"""

from __future__ import annotations

import os

from backend.engineering_control_plane.config import Settings
from backend.engineering_control_plane.database import apply_migrations


def main() -> None:
    apply_migrations(Settings.from_environment())
    os.execvp(
        "python",
        [
            "python",
            "-m",
            "uvicorn",
            "backend.engineering_control_plane.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )


if __name__ == "__main__":
    main()

