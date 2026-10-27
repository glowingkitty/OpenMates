"""Claude request controls from explicit actual-server catalog declarations."""
from typing import Any

from backend.core.api.app.utils.config_manager import config_manager


def claude_reasoning_body(model_id: str, server_id: str, effort: str | None) -> dict[str, Any]:
    """Validate an optional native effort and produce Claude wire fields.

    Catalog matching uses the actual server model ID, including Bedrock profile
    IDs. Unknown routes and fixed variants never gain controls via name prefixes.
    """
    if effort is None:
        return {}
    provider = config_manager.get_provider_config("anthropic") or {}
    for model in provider.get("models", []):
        if (model.get("reasoning_control") or {}).get("fixed"):
            continue
        for server in model.get("servers") or []:
            if server.get("id") != server_id or server.get("model_id") != model_id:
                continue
            control = server.get("reasoning_control") or {}
            if control.get("fixed") or control.get("parameter") != "reasoning_effort":
                return {}
            if effort not in (control.get("levels") or {}).values():
                raise ValueError("Unsupported reasoning effort for the declared Claude route")
            body = {"output_config": {"effort": effort}}
            if control.get("adaptive_thinking"):
                body["thinking"] = {"type": "adaptive"}
            return body
    return {}
