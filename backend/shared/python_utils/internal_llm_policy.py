"""The user's AI model settings, applied to LLM steps that run inside app skills.

Skills such as images.generate, images.modify and videos.generate call an LLM
themselves (authoring a drawing, a picture edit or a video composition, or
choosing a route). Those steps follow the same user settings as the chat:

* When the user saved a model for complex tasks (``default_ai_model_complex``)
  and it can take the step's inputs, that model alone answers.
* A model or server the user turned off (``disabled_ai_models``,
  ``disabled_ai_servers``) is never called, and the server region preference is
  passed on.
* Without such settings the skill's own default models answer exactly as before.

The policy is built once per chat turn by the AI pipeline, travels to the skill
as the hidden ``_internal_llm_policy`` argument and to media worker tasks inside
their payload (``to_payload`` / ``from_payload``).
Spec: specifications/features/ai-model-routing (skill-internal model steps).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

POLICY_ARGUMENT = "_internal_llm_policy"
_REGIONS = ("eu", "global")
_MAX_ENTRIES = 256


@dataclass(frozen=True)
class InternalModelRoute:
    """One permitted author model and the servers it may use (None: any server)."""

    model_id: str
    allowed_server_ids: Optional[frozenset[str]] = None
    user_selected: bool = False


@dataclass(frozen=True)
class InternalLlmPolicy:
    complex_model: Optional[str] = None
    disabled_ai_models: frozenset[str] = frozenset()
    disabled_ai_servers: Mapping[str, frozenset[str]] = field(default_factory=dict)
    server_region_preference: str = "eu"

    # --- construction -----------------------------------------------------------------

    @classmethod
    def from_user_preferences(cls, preferences: Optional[Mapping[str, Any]]) -> "InternalLlmPolicy":
        """Build the policy from the turn's merged user preferences (main pipeline)."""
        return cls.from_payload(dict(preferences or {}), source="user_preferences")

    @classmethod
    def from_payload(cls, value: Any, *, source: str = "payload") -> "InternalLlmPolicy":
        """Parse a policy; anything malformed is dropped field by field, never guessed."""
        if not isinstance(value, Mapping):
            return cls()
        complex_model = value.get("default_ai_model_complex", value.get("complex_model"))
        if not (isinstance(complex_model, str) and complex_model.count("/") == 1 and all(complex_model.split("/"))):
            if complex_model not in (None, "", "auto"):
                logger.warning("Ignoring invalid complex model in %s: %r", source, complex_model)
            complex_model = None
        disabled_models = value.get("disabled_ai_models") or []
        models = frozenset(m for m in disabled_models[:_MAX_ENTRIES] if isinstance(m, str)) \
            if isinstance(disabled_models, (list, tuple, set, frozenset)) else frozenset()
        disabled_servers = value.get("disabled_ai_servers") or {}
        servers: dict[str, frozenset[str]] = {}
        if isinstance(disabled_servers, Mapping):
            for model, ids in list(disabled_servers.items())[:_MAX_ENTRIES]:
                if isinstance(model, str) and isinstance(ids, (list, tuple, set, frozenset)):
                    servers[model] = frozenset(s for s in ids if isinstance(s, str))
        region = value.get("server_region_preference")
        return cls(
            complex_model=complex_model, disabled_ai_models=models, disabled_ai_servers=servers,
            server_region_preference=region if region in _REGIONS else "eu",
        )

    def to_payload(self) -> Optional[dict[str, Any]]:
        """JSON form for skill arguments and worker payloads; None when nothing is set."""
        if self.is_default:
            return None
        return {
            "complex_model": self.complex_model,
            "disabled_ai_models": sorted(self.disabled_ai_models),
            "disabled_ai_servers": {k: sorted(v) for k, v in sorted(self.disabled_ai_servers.items())},
            "server_region_preference": self.server_region_preference,
        }

    @property
    def is_default(self) -> bool:
        return (self.complex_model is None and not self.disabled_ai_models
                and not any(self.disabled_ai_servers.values()) and self.server_region_preference == "eu")

    # --- restrictions -----------------------------------------------------------------

    def _restriction_preferences(self) -> dict[str, Any]:
        return {
            "disabled_ai_models": list(self.disabled_ai_models),
            "disabled_ai_servers": {k: list(v) for k, v in self.disabled_ai_servers.items()},
        }

    def allowed_servers(self, model_ref: str, provider_config: Optional[Mapping[str, Any]] = None) -> frozenset[str]:
        """Servers of ``provider/model`` the user permits; empty when the model is off or unknown."""
        from backend.apps.ai.processing.model_routing import automatic_model_allowed_servers

        if provider_config is None:
            from backend.core.api.app.utils.config_manager import config_manager

            provider_config = config_manager.get_provider_config(model_ref.split("/", 1)[0])
        return frozenset(automatic_model_allowed_servers(model_ref, self._restriction_preferences(), provider_config))

    def _route_for(self, model_ref: str, required_inputs: Sequence[str], *, user_selected: bool,
                   provider_config: Optional[Mapping[str, Any]] = None) -> Optional[InternalModelRoute]:
        from backend.core.api.app.utils.config_manager import config_manager

        provider_id, model_id = model_ref.split("/", 1)
        model = config_manager.get_model_pricing(provider_id, model_id)
        if not isinstance(model, Mapping):
            return None
        if user_selected:
            from backend.shared.python_utils.model_availability import is_model_available

            if model.get("for_app_skill") != "ai.ask" or not is_model_available(dict(model)):
                return None
        input_types = set(model.get("input_types") or ["text"])
        if not set(required_inputs) <= input_types:
            return None
        servers = self.allowed_servers(model_ref, provider_config)
        if not servers:
            return None
        restricted = bool(self.disabled_ai_servers.get(model_id) or self.disabled_ai_servers.get(model_ref))
        return InternalModelRoute(model_ref, servers if restricted else None, user_selected)

    def author_routes(self, defaults: Iterable[str], *, required_inputs: Sequence[str] = ("text",),
                      task_id: str = "-") -> tuple[InternalModelRoute, ...]:
        """Ordered author models for one skill step.

        The saved complex model alone answers when it can take ``required_inputs``
        and the user has not turned it off; otherwise the skill's default chain
        minus every model the user turned off. With no settings this returns the
        defaults unchanged (no lookups), so existing behavior is kept exactly.
        """
        default_list = tuple(dict.fromkeys(defaults))
        if self.is_default:
            return tuple(InternalModelRoute(m) for m in default_list)
        if self.complex_model:
            chosen = self._route_for(self.complex_model, required_inputs, user_selected=True)
            if chosen:
                logger.info("[%s] Skill-internal LLM step uses the user's complex model %s", task_id, chosen.model_id)
                return (chosen,)
            logger.info("[%s] User's complex model %s cannot take %s for this step; using permitted defaults",
                        task_id, self.complex_model, "+".join(required_inputs))
        routes = tuple(r for m in default_list
                       if (r := self._route_for(m, required_inputs, user_selected=False)) is not None)
        if len(routes) != len(default_list):
            logger.info("[%s] User AI settings removed %d default skill-internal model(s)", task_id,
                        len(default_list) - len(routes))
        return routes

    def stream_options(self, route: InternalModelRoute) -> dict[str, Any]:
        """Keyword arguments for ``call_main_llm_stream`` that carry the restrictions."""
        if self.is_default and route.allowed_server_ids is None:
            return {}
        options: dict[str, Any] = {"server_region_preference": self.server_region_preference}
        if route.allowed_server_ids is not None:
            options["allowed_server_ids"] = set(route.allowed_server_ids)
        return options


DEFAULT_POLICY = InternalLlmPolicy()


def policy_from_skill_kwargs(kwargs: Mapping[str, Any]) -> InternalLlmPolicy:
    """Read the policy a skill received (``internal_llm_policy`` kwarg) or a task payload."""
    value = kwargs.get("internal_llm_policy")
    if isinstance(value, InternalLlmPolicy):
        return value
    return InternalLlmPolicy.from_payload(value, source="skill")
