# frontend/apps/web_app/tests/fixtures/code_run_requests.py
#
# Python fixture for Code Run E2E coverage. It intentionally imports a third-party
# package and uses a harmless api_key variable name to ensure the sandbox flow
# suggests dependencies without falsely blocking ordinary code as a secret leak.

from pathlib import Path

import requests


def main() -> None:
    """Exercise dependency detection while keeping execution deterministic."""
    api_key = None
    params = {"q": "Berlin", "appid": api_key, "units": "metric"}
    _ = requests.Request("GET", "https://example.invalid/weather", params=params)
    output = Path("outputs/result.txt")
    output.parent.mkdir(exist_ok=True)
    output.write_text("Hello, World!\n", encoding="utf-8")
    print("Hello, World!")


if __name__ == "__main__":
    main()
