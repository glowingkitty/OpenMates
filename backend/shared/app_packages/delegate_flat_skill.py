"""Generic delegate for paused built-in skills with a flat tool schema.

A paused skill whose public ``tool_schema`` has no top-level ``requests`` array
(``generic_contract.is_flat_schema``) is served by ``InstalledProviderFlatSkill``.
Everything is derived from the original skill module, never from skill names:

1. the tool input is the call's keyword arguments named by the skill's public
   ``tool_schema`` properties; it is validated by the original request model
   (the module's single ``*Request`` model without a ``requests`` field, or a
   typed ``execute`` argument), with null optional fields dropped as for items;
2. the whole validated input is the single ``skill.requests@1`` item (``input``)
   sent to every installed provider, or to the providers the call selects in
   ``provider`` / ``providers`` / ``provider_platform``;
3. the response is the original ``*Response`` model defaults with: the results
   (round-robin across providers) in the model's ``results`` field, else its first
   list-of-objects field; input values the model declares under the same name
   (``match`` -> ``match``) or as the singular of a list input (``queries`` ->
   ``query``, joined with ", "); and ``provider``, ``providers``, ``error``,
   ``result_count``, ``success``, ``partial`` and ``warnings`` when declared.

Fields that describe the execution itself (``status``, ``success``, ``error``, ...)
are never copied from the input. Billing never reads this output.
Architecture: docs/architecture/apps/instance-app-packages.md ("Generic contract").
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Type, get_args, get_origin

from pydantic import BaseModel, ValidationError

from backend.shared.app_packages.delegate_skill import (
    UNAVAILABLE_ERROR,
    DelegateConfigurationError,
    InstalledProviderSkill,
    accepts_payload,
    build_group,
    covered_providers,
    error_group,
    import_original_skill,
    is_model,
    keep_selectors,
    module_models,
    report_provider,
    validate_request_item,
    with_warnings,
)
from backend.shared.app_packages.generic_contract import PROVIDER_SELECTOR_FIELDS
from backend.apps.skill_progress import SkillProgress
from backend.shared.app_packages.loader import InstalledProvider
from backend.shared.app_packages.provider_dispatch import run_installed_providers

logger = logging.getLogger(__name__)

DEFAULT_RESULTS_FIELD = "results"
# Response fields that describe the execution; never filled from the tool input.
EXECUTION_FIELDS: FrozenSet[str] = frozenset({
    "success", "status", "app_id", "skill_id", "provider", "providers", "error", "error_code",
    "warnings", "result_count", "partial",
})
SCALAR_TYPES = (str, int, float)


@dataclass(frozen=True)
class FlatSkillModels:
    """Request model and response shape of an original flat-schema skill."""

    request_model: Optional[Type[BaseModel]]
    response_model: Optional[Type[BaseModel]]
    response_defaults: Dict[str, Any]
    results_field: str = DEFAULT_RESULTS_FIELD
    provider_objects: bool = False


# --------------------------------------------------------------------------
# Original model resolution
# --------------------------------------------------------------------------

def _flat_request_model(skill_class: type, module: ModuleType) -> Optional[Type[BaseModel]]:
    execute = getattr(skill_class, "execute", None)
    if execute is not None:
        params = [p for name, p in inspect.signature(execute).parameters.items() if name != "self"]
        first = next((p for p in params if p.default is inspect.Parameter.empty
                      and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)), None)
        if first is not None and is_model(first.annotation) and "requests" not in first.annotation.model_fields:
            return first.annotation
    candidates = [model for name, model in module_models(module)
                  if name.endswith("Request") and "requests" not in model.model_fields]
    return candidates[0] if len(candidates) == 1 else None


def _is_object_list(annotation: Any) -> bool:
    """``list[dict]`` / ``List[Dict[...]]`` / ``list[Model]``, also inside ``Optional``."""
    if get_origin(annotation) in (list, List):
        args = get_args(annotation)
        item = args[0] if args else None
        return item is dict or get_origin(item) is dict or is_model(item)
    return any(_is_object_list(arg) for arg in get_args(annotation))


def _results_field(model: Type[BaseModel]) -> Optional[str]:
    if DEFAULT_RESULTS_FIELD in model.model_fields:
        return DEFAULT_RESULTS_FIELD
    return next((name for name, field in model.model_fields.items()
                 if name not in EXECUTION_FIELDS and _is_object_list(field.annotation)), None)


@lru_cache(maxsize=64)
def resolve_flat_skill_models(class_path: str) -> FlatSkillModels:
    """Resolve the request model and response shape of the original flat skill class."""
    module, skill_class = import_original_skill(class_path)
    request_model = _flat_request_model(skill_class, module)
    if request_model is None:
        logger.info("[AppPackages] No request model found for %s; the input is passed as a JSON object", class_path)
    for name, model in module_models(module):
        if not name.endswith("Response"):
            continue
        results_field = _results_field(model)
        if results_field is None:
            continue
        try:
            defaults = model.model_validate({}).model_dump(mode="json")
        except ValidationError:
            logger.debug("[AppPackages] %s.%s has required fields; not used as response base", module.__name__, name)
            continue
        provider_objects = (
            not accepts_payload(model, {"providers": ["p"]})
            and accepts_payload(model, {"providers": [{"id": "p", "name": "P"}]})
        )
        return FlatSkillModels(request_model, model, defaults, results_field, provider_objects)
    return FlatSkillModels(request_model, None, {})


# --------------------------------------------------------------------------
# Response shaping
# --------------------------------------------------------------------------

def _plural_names(name: str) -> List[str]:
    names = [f"{name}s"]
    if name.endswith("y"):
        names.append(f"{name[:-1]}ies")
    return names


def echoed_input_fields(models: FlatSkillModels, contract_input: Dict[str, Any]) -> Dict[str, Any]:
    """Input values the original response model declares (same name, or singular of a list)."""
    model = models.response_model
    if model is None:
        return {}
    owned = EXECUTION_FIELDS | {models.results_field}
    echoed: Dict[str, Any] = {
        key: value for key, value in contract_input.items()
        if key in model.model_fields and key not in owned and accepts_payload(model, {key: value})
    }
    for name in model.model_fields:
        if name in echoed or name in owned:
            continue
        values = next((contract_input[plural] for plural in _plural_names(name) if plural in contract_input), None)
        if not isinstance(values, list) or not values:
            continue
        if not all(isinstance(value, SCALAR_TYPES) and not isinstance(value, bool) for value in values):
            continue
        joined = ", ".join(str(value) for value in values)
        if accepts_payload(model, {name: joined}):
            echoed[name] = joined
    return echoed


def build_flat_response(group: Dict[str, Any], providers: Sequence[InstalledProvider], models: FlatSkillModels,
                        echoed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The original flat response shape filled from one served (or failed) group."""
    names = {provider.provider_id: provider.name for provider in providers}
    contributed: List[str] = list(group.get("providers") or [])
    shown = contributed or [provider.provider_id for provider in providers]
    error = group.get("error")
    defaults = models.response_defaults
    response: Dict[str, Any] = {
        **defaults,
        **(echoed or {}),
        models.results_field: list(group.get("results") or []),
        "provider": ", ".join(names[pid] for pid in shown if pid in names) or "Unavailable",
        "providers": [{"id": pid, "name": names.get(pid, pid)} for pid in contributed]
        if models.provider_objects else contributed,
        "error": error or None,
    }
    if "result_count" in defaults:
        response["result_count"] = len(response[models.results_field])
    if "success" in defaults:
        response["success"] = not error
    warnings = group.get("warnings")
    if warnings:
        response["warnings"] = list(warnings)
        if "partial" in defaults:
            response["partial"] = True
    return response


class InstalledProviderFlatSkill(InstalledProviderSkill):
    """Serve a paused flat-schema skill: the whole tool input is the single request item."""

    def _input_names(self) -> FrozenSet[str]:
        definition = self.app.get_skill_by_id(self.skill_id) if self.app is not None else None
        schema = getattr(definition, "tool_schema", None)
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict) or not properties:
            raise DelegateConfigurationError(f"{self.app_id}.{self.skill_id} has no tool_schema properties")
        return frozenset(properties)

    async def execute(self, secrets_manager: Any = None, **kwargs: Any) -> Dict[str, Any]:
        models = resolve_flat_skill_models(self._original_class_path())
        providers = self._providers()
        # Context kwargs (user, chat, services) are not part of the public tool input.
        names = self._input_names()
        raw = {key: value for key, value in kwargs.items() if key in names}
        if not providers:
            return build_flat_response(error_group(None, UNAVAILABLE_ERROR), providers, models)
        contract_input, error = validate_request_item(models.request_model, raw)
        if contract_input is None:
            return build_flat_response(error_group(None, error or "Invalid request."), providers, models)
        # Selectors are read from the call: the request model may not declare them.
        selectors = {key: kwargs[key] for key in PROVIDER_SELECTOR_FIELDS if key in kwargs}
        # Providers whose declared regions the call does not name are not started.
        providers, skipped, coverage_error = covered_providers({**raw, **selectors}, providers)
        if coverage_error:
            return build_flat_response(error_group(None, coverage_error), providers, models)
        provider_ids = [provider.provider_id for provider in providers]
        progress = SkillProgress(self)
        await progress.add_sources(len(provider_ids))
        outcomes = await run_installed_providers(
            self.app_id, self.skill_id, provider_ids,
            keep_selectors(contract_input, selectors), secrets_manager,
            on_provider_done=report_provider(progress),
        )
        return build_flat_response(with_warnings(build_group(None, outcomes), skipped), providers, models,
                                   echoed_input_fields(models, contract_input))
