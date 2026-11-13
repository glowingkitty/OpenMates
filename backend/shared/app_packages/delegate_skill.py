"""Generic skill class for paused built-in skills served by installed providers.

The app package overlay points ``class_path`` of an eligible skill (see
``generic_contract.accepts_generic_contract``) at ``InstalledProviderSkill`` and
keeps the original path in ``delegated_class_path``. This class:

1. validates each request item with the original skill's request item model
   (resolved from its module; plain JSON objects when none can be resolved);
2. runs the installed ``skill.requests@1`` providers of this (app, skill) for
   each item concurrently through the isolated runner, or only the providers
   the item selects by id or name in ``provider`` / ``providers`` /
   ``provider_platform``;
3. merges each item's results round-robin across providers (stable registry
   order, no server-side caps or sorting) and returns the standard grouped
   response, built on the original skill's
   response model defaults when one can be resolved.

Provider failures become short safe per-group messages. Billing never reads
this output: the registry decides (``billing.served_only_by_installed_providers``).
Skills with a flat tool schema use the subclass in ``delegate_flat_skill``.
Architecture: docs/architecture/apps/instance-app-packages.md ("Generic contract").
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Type, get_args, get_origin

from pydantic import BaseModel, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.apps.skill_progress import SkillProgress
from backend.shared.app_packages.generic_contract import (
    GENERIC_CONTRACTS,
    PROVIDER_SELECTOR_FIELDS,
    filter_providers_by_region,
)
from backend.shared.app_packages.loader import InstalledProvider, get_installed_providers
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome, run_installed_providers
from backend.shared.app_packages.web_source import delegate_web_kind, run_web_source
from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy, policy_from_skill_kwargs
from backend.shared.app_packages.result_photo_relevance import (
    CRITERIA_FIELD,
    rank_results_by_photos,
    request_projection,
    requested_limit,
    wants_photo_ranking,
    widen_candidate_pool,
)

logger = logging.getLogger(__name__)

MAX_REQUESTS_PER_CALL = 10
MAX_VALIDATION_ERRORS_SHOWN = 3
UNAVAILABLE_ERROR = "No installed provider is available for this capability."
TOO_MANY_REQUESTS_ERROR = f"At most {MAX_REQUESTS_PER_CALL} requests are served per call."


class DelegateConfigurationError(RuntimeError):
    """The skill metadata does not name a resolvable original skill class."""


@dataclass(frozen=True)
class OriginalSkillModels:
    """Public models of the original skill used to validate input and shape output."""

    item_model: Optional[Type[BaseModel]]
    response_defaults: Dict[str, Any]
    # True when the original response lists providers as {"id", "name"} objects.
    provider_objects: bool = False


# --------------------------------------------------------------------------
# Original skill model resolution
# --------------------------------------------------------------------------

def is_model(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel


def _list_item_model(annotation: Any) -> Optional[Type[BaseModel]]:
    """``List[X]`` / ``list[X]`` / ``Optional[List[X]]`` -> X when X is a model."""
    if get_origin(annotation) in (list, List):
        args = get_args(annotation)
        return args[0] if args and is_model(args[0]) else None
    for arg in get_args(annotation):
        found = _list_item_model(arg)
        if found is not None:
            return found
    return None


def _requests_item_model(model: Type[BaseModel]) -> Optional[Type[BaseModel]]:
    field = model.model_fields.get("requests")
    return _list_item_model(field.annotation) if field is not None else None


def module_models(module: ModuleType) -> List[Tuple[str, Type[BaseModel]]]:
    return [
        (name, value) for name, value in vars(module).items()
        if is_model(value) and value.__module__ == module.__name__
    ]


def _execute_item_model(skill_class: type) -> Optional[Type[BaseModel]]:
    """Item model from a typed ``execute(request: XRequest)`` or ``execute(requests: List[X])``."""
    execute = getattr(skill_class, "execute", None)
    if execute is None:
        return None
    params = [p for name, p in inspect.signature(execute).parameters.items() if name != "self"]
    first = next((p for p in params if p.default is inspect.Parameter.empty
                  and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)), None)
    if first is None or isinstance(first.annotation, str):
        return None
    if is_model(first.annotation):
        return _requests_item_model(first.annotation)
    return _list_item_model(first.annotation)


def _resolve_item_model(skill_class: type, module: ModuleType) -> Optional[Type[BaseModel]]:
    from_signature = _execute_item_model(skill_class)
    if from_signature is not None:
        return from_signature
    models = module_models(module)
    from_request = list(dict.fromkeys(
        item for name, model in models if name.endswith("Request")
        and (item := _requests_item_model(model)) is not None
    ))
    if len(from_request) == 1:
        return from_request[0]
    items = [model for name, model in models if name.endswith("RequestItem")]
    return items[0] if len(items) == 1 else None


def accepts_payload(model: Type[BaseModel], payload: Dict[str, Any]) -> bool:
    try:
        model.model_validate(payload)
    except ValidationError:
        return False
    return True


def _resolve_response_shape(module: ModuleType) -> Tuple[Dict[str, Any], bool]:
    """Response defaults and whether the original model lists providers as objects."""
    for name, model in module_models(module):
        if not name.endswith("Response") or "results" not in model.model_fields:
            continue
        try:
            defaults = model.model_validate({"results": []}).model_dump(mode="json")
        except ValidationError:
            logger.debug("[AppPackages] %s.%s needs more than results; not used as response base",
                         module.__name__, name)
            continue
        provider_objects = (
            not accepts_payload(model, {"results": [], "providers": ["p"]})
            and accepts_payload(model, {"results": [], "providers": [{"id": "p", "name": "P"}]})
        )
        return defaults, provider_objects
    return {}, False


def import_original_skill(class_path: str) -> Tuple[ModuleType, type]:
    """Import the original skill module and class named by ``delegated_class_path``."""
    module_path, _, class_name = class_path.strip().rpartition(".")
    if not module_path:
        raise DelegateConfigurationError(f"invalid delegated class path '{class_path}'")
    if not module_path.startswith("backend."):
        module_path = f"backend.apps.{module_path}"
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise DelegateConfigurationError(f"cannot import '{module_path}': {exc}") from exc
    skill_class = getattr(module, class_name, None)
    if not isinstance(skill_class, type):
        raise DelegateConfigurationError(f"'{class_path}' is not a class")
    return module, skill_class


@lru_cache(maxsize=64)
def resolve_original_skill_models(class_path: str) -> OriginalSkillModels:
    """Resolve the request item model and response defaults of the original skill class."""
    module, skill_class = import_original_skill(class_path)
    item_model = _resolve_item_model(skill_class, module)
    if item_model is None:
        logger.info("[AppPackages] No request item model found for %s; items are passed as JSON objects", class_path)
    response_defaults, provider_objects = _resolve_response_shape(module)
    return OriginalSkillModels(item_model=item_model, response_defaults=response_defaults,
                               provider_objects=provider_objects)


# --------------------------------------------------------------------------
# Request handling
# --------------------------------------------------------------------------

def _validation_message(exc: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(part) for part in error.get('loc', ())) or 'request'}: {error.get('msg', 'invalid')}"
        for error in exc.errors()[:MAX_VALIDATION_ERRORS_SHOWN]
    ]
    return "Invalid request: " + "; ".join(parts)


def validate_request_item(item_model: Optional[Type[BaseModel]], raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (contract input, None) or (None, safe error) for one request item."""
    if not isinstance(raw, dict):
        return None, "Invalid request: each request must be an object."
    if item_model is None:
        return dict(raw), None
    # Callers send unset optional fields as null; the model defaults apply to those.
    provided = {key: value for key, value in raw.items() if value is not None}
    try:
        validated = item_model.model_validate(provided)
    except ValidationError as exc:
        return None, _validation_message(exc)
    return validated.model_dump(mode="json", exclude_none=True), None


def select_provider_ids(item: Dict[str, Any], providers: Sequence[InstalledProvider]) -> List[str]:
    """Installed providers named by the item (id or display name), else every provider."""
    lookup: Dict[str, str] = {}
    for provider in providers:
        lookup[provider.name.strip().casefold()] = provider.provider_id
        lookup[provider.provider_id] = provider.provider_id
    values: List[Any] = []
    for field in PROVIDER_SELECTOR_FIELDS:
        value = item.get(field)
        values.extend(value if isinstance(value, list) else [value])
    chosen = [lookup[key] for value in values if isinstance(value, str)
              and (key := value.strip().casefold()) in lookup]
    return list(dict.fromkeys(chosen)) or [provider.provider_id for provider in providers]


def names_providers(item: Any) -> bool:
    """True when the request item names the providers to use."""
    if not isinstance(item, dict):
        return False
    return any(isinstance(value, str) and value.strip().casefold() not in ("", "auto")
               for field in PROVIDER_SELECTOR_FIELDS
               for value in (item[field] if isinstance(item.get(field), list) else [item.get(field)]))


def keep_selectors(contract_input: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """Contract input plus the selector fields of the call that the item model dropped.

    A provider that serves several sources needs the caller's choice to route the request.
    """
    kept = {field: raw[field] for field in PROVIDER_SELECTOR_FIELDS
            if field not in contract_input and isinstance(raw.get(field), (str, list)) and raw[field]}
    return {**contract_input, **kept}


def interleave_results(per_provider: Sequence[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Round-robin merge: first result of each provider, then the second of each, ..."""
    merged: List[Dict[str, Any]] = []
    for position in range(max((len(results) for results in per_provider), default=0)):
        merged.extend(results[position] for results in per_provider if position < len(results))
    return merged


def build_group(request_id: Any, outcomes: Sequence[InstalledProviderOutcome]) -> Dict[str, Any]:
    """One grouped result; ``providers`` lists the ids that contributed results.

    Results are interleaved round-robin across providers in their stable order
    (registry order), so no single provider crowds out the others.
    """
    results = interleave_results([outcome.results for outcome in outcomes])
    failures = list(dict.fromkeys(outcome.error for outcome in outcomes if outcome.error))
    group: Dict[str, Any] = {
        "id": request_id,
        "results": results,
        "providers": list(dict.fromkeys(result["provider_id"] for result in results)),
    }
    if failures and not results:
        group["error"] = " ".join(failures)
    elif failures:
        group["warnings"] = failures
    return group


def error_group(request_id: Any, message: str) -> Dict[str, Any]:
    return {"id": request_id, "results": [], "providers": [], "error": message}


def covered_providers(raw: Dict[str, Any], providers: Sequence[InstalledProvider]
                      ) -> Tuple[List[InstalledProvider], List[str], Optional[str]]:
    """The selected providers that cover the request's regions, skip warnings and a coverage error.

    Providers declaring ``regions`` that the request does not name are never started.
    """
    selected = select_provider_ids(raw, providers)
    kept, skipped, coverage_error = filter_providers_by_region(selected, providers, raw)
    return [provider for provider in providers if provider.provider_id in kept], skipped, coverage_error


def with_warnings(group: Dict[str, Any], warnings: Sequence[str]) -> Dict[str, Any]:
    """The group with extra warnings appended once each."""
    if warnings:
        group["warnings"] = list(dict.fromkeys([*group.get("warnings", []), *warnings]))
    return group


def build_response(groups: List[Dict[str, Any]], providers: Sequence[InstalledProvider],
                   response_defaults: Dict[str, Any], provider_objects: bool = False) -> Dict[str, Any]:
    """Standard grouped skill response on top of the original response model defaults."""
    names = {provider.provider_id: provider.name for provider in providers}
    contributed = list(dict.fromkeys(pid for group in groups for pid in group.get("providers", [])))
    shown = contributed or [provider.provider_id for provider in providers]
    all_failed = bool(groups) and all(group.get("error") for group in groups)
    errors = list(dict.fromkeys(group["error"] for group in groups if group.get("error")))
    warnings = [warning for group in groups for warning in group.get("warnings", [])]
    response: Dict[str, Any] = {
        **response_defaults,
        "results": groups,
        "provider": ", ".join(names[pid] for pid in shown if pid in names) or "Unavailable",
        "providers": [{"id": pid, "name": names.get(pid, pid)} for pid in contributed]
        if provider_objects else contributed,
        "error": "; ".join(errors) if all_failed else None,
    }
    if warnings:
        response["warnings"] = list(dict.fromkeys(warnings))
    if "success" in response_defaults:
        response["success"] = not all_failed
    return response


def report_provider(progress: Optional[SkillProgress]) -> Optional[Callable[[InstalledProviderOutcome], Awaitable[None]]]:
    """``on_provider_done`` callback counting each finished provider on ``progress``."""
    if progress is None:
        return None

    async def report(outcome: InstalledProviderOutcome) -> None:
        await progress.source_done(len(outcome.results))

    return report


class InstalledProviderSkill(BaseSkill):
    """Serve a paused built-in skill through its installed ``skill.requests@1`` providers."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        # The serving providers are only known per request at execution time.
        return {}

    def _original_class_path(self) -> str:
        definition = self.app.get_skill_by_id(self.skill_id) if self.app is not None else None
        class_path = getattr(definition, "delegated_class_path", None)
        if not isinstance(class_path, str) or not class_path.strip():
            raise DelegateConfigurationError(f"{self.app_id}.{self.skill_id} has no delegated_class_path")
        return class_path

    def _providers(self) -> List[InstalledProvider]:
        return [p for p in get_installed_providers(self.app_id, self.skill_id) if p.contract in GENERIC_CONTRACTS]

    async def _serve_covered(self, index: int, raw: Any, models: OriginalSkillModels,
                             providers: Sequence[InstalledProvider], secrets_manager: Any,
                             progress: Optional[SkillProgress] = None,
                             policy: Optional[InternalLlmPolicy] = None) -> Dict[str, Any]:
        """Serve one item with only the providers covering its regions; skipped ones become warnings."""
        if index >= MAX_REQUESTS_PER_CALL or not providers or not isinstance(raw, dict):
            return await self._serve_item(index, raw, models, providers, secrets_manager, progress, policy)
        # Selectors and regions are read from the raw item: the item model may not declare them.
        covered, skipped, coverage_error = covered_providers(raw, providers)
        if coverage_error:
            return error_group(raw.get("id") if raw.get("id") is not None else index + 1, coverage_error)
        return with_warnings(
            await self._serve_item(index, raw, models, covered, secrets_manager, progress, policy), skipped)

    async def _serve_item(self, index: int, raw: Any, models: OriginalSkillModels,
                          providers: Sequence[InstalledProvider], secrets_manager: Any,
                          progress: Optional[SkillProgress] = None,
                          policy: Optional[InternalLlmPolicy] = None) -> Dict[str, Any]:
        """Serve one request item. ``progress`` counts this item's sources across the whole call."""
        request_id = raw.get("id") if isinstance(raw, dict) and raw.get("id") is not None else index + 1
        if index >= MAX_REQUESTS_PER_CALL:
            return error_group(request_id, TOO_MANY_REQUESTS_ERROR)
        if not providers:
            return error_group(request_id, UNAVAILABLE_ERROR)
        contract_input, error = validate_request_item(models.item_model, raw)
        if contract_input is None:
            return error_group(request_id, error or "Invalid request.")
        ranked = wants_photo_ranking(self.app_id, self.skill_id, contract_input)
        provider_input = keep_selectors(contract_input, raw)
        # Selectors are read from the raw item: the item model may not declare them.
        provider_ids = select_provider_ids(raw, providers)
        # The web is searched too unless the caller named the providers to use.
        web_kind = None if names_providers(raw) else delegate_web_kind(self.app_id, self.skill_id)
        if progress is not None:
            await progress.add_sources(len(provider_ids) + int(web_kind is not None))
        searches: List[Awaitable[Any]] = [run_installed_providers(
            self.app_id, self.skill_id, provider_ids,
            widen_candidate_pool(provider_input) if ranked else provider_input, secrets_manager,
            on_provider_done=report_provider(progress),
        )]
        if web_kind is not None:
            searches.append(self._search_web(web_kind, contract_input, secrets_manager, progress))
        outcomes, *web_outcomes = await asyncio.gather(*searches)
        outcomes = [*outcomes, *web_outcomes]
        group = build_group(request_id, outcomes)
        if ranked and group["results"]:
            await self._rank_group(group, contract_input, secrets_manager, policy)
        return group

    async def _search_web(self, kind: str, contract_input: Dict[str, Any], secrets_manager: Any,
                          progress: Optional[SkillProgress]) -> InstalledProviderOutcome:
        outcome = await run_web_source(kind, contract_input, secrets_manager)
        if progress is not None:
            await progress.source_done(len(outcome.results))
        return outcome

    async def _rank_group(self, group: Dict[str, Any], contract_input: Dict[str, Any], secrets_manager: Any,
                          policy: Optional[InternalLlmPolicy] = None) -> None:
        """Order the group by criteria fit judged on result photos; then apply the requested limit."""
        ranking = await rank_results_by_photos(
            group["results"], relevance_criteria=contract_input[CRITERIA_FIELD],
            searched=request_projection(contract_input), secrets_manager=secrets_manager, policy=policy,
        )
        limit = requested_limit(contract_input)
        group["results"] = ranking.results[:limit] if limit else ranking.results
        group["providers"] = list(dict.fromkeys(result["provider_id"] for result in group["results"]))
        group["relevance_ranking"] = "photos_and_facts" if ranking.applied else "unavailable"

    async def execute(self, requests: List[Dict[str, Any]], secrets_manager: Any = None,
                      **kwargs: Any) -> Dict[str, Any]:
        models = resolve_original_skill_models(self._original_class_path())
        providers = self._providers()
        items = [requests] if isinstance(requests, dict) else list(requests or [])
        progress = SkillProgress(self)
        policy = policy_from_skill_kwargs(kwargs)
        groups = list(await asyncio.gather(*(
            self._serve_covered(index, item, models, providers, secrets_manager, progress, policy)
            for index, item in enumerate(items)
        )))
        return build_response(groups, providers, models.response_defaults, models.provider_objects)
