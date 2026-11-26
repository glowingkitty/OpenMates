"""An explicit tunnel for the isolated, provider-billed web voice proof."""

import os

_RUNNER_PROXY = "http://runner-gateway:3128"


def isolated_voice_websocket_proxy() -> str | None:
    """Use the fixed CI gateway only for the dedicated voice proof services."""
    if os.environ.get("OPENMATES_CI_REAL_WEB_VOICE") != "1":
        return None
    if (
        os.environ.get("CI") != "true"
        or os.environ.get("OPENMATES_CI_ISOLATED") != "1"
        or os.environ.get("OPENMATES_CI_REAL_INFERENCE") != "1"
        or os.environ.get("OPENMATES_CI_AI_FIXTURES") == "1"
        or os.environ.get("SERVER_ENVIRONMENT") != "development"
    ):
        raise RuntimeError("The web voice proxy requires an isolated real-inference service")
    return _RUNNER_PROXY
