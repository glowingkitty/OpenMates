"""Shared result shape and errors for official company register providers.

Every register wrapper returns the same normalized dicts so the Business app
can render one ownership record regardless of country. Wrappers drop private
personal data (birth dates, private addresses, nationality, identity data)
before anything leaves this package.
"""

from __future__ import annotations

from typing import Any

# Fields that must never appear in a normalized record, whatever the source.
PRIVATE_PERSON_FIELDS = frozenset(
    {
        "date_of_birth",
        "date_de_naissance",
        "annee_de_naissance",
        "birth_date",
        "age",
        "nationality",
        "nationalite",
        "country_of_residence",
        "address",
        "occupation",
        "identification",
    }
)


class RegisterProviderError(Exception):
    """Typed provider failure with a stable error code for the skill layer."""

    def __init__(self, code: str, message: str, candidates: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates or []


def company_subject(
    *,
    name: str,
    country: str,
    register_id: str | None = None,
    legal_form: str | None = None,
    status: str | None = None,
    city: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Build the normalized subject block for a company."""
    return {
        "name": name,
        "type": "company",
        "country": country,
        "register_id": register_id,
        "legal_form": legal_form,
        "status": status,
        "city": city,
        "source_url": source_url,
    }


def person_subject(*, name: str, country: str, city: str | None = None, source_url: str | None = None) -> dict[str, Any]:
    """Build the normalized subject block for a natural person (no birth data)."""
    return {
        "name": name,
        "type": "person",
        "country": country,
        "register_id": None,
        "legal_form": None,
        "status": None,
        "city": city,
        "source_url": source_url,
    }


def owner(
    *,
    name: str,
    owner_type: str,
    share_percent: float | None = None,
    share_band: str | None = None,
    nominal_amount: float | None = None,
    currency: str | None = None,
    since: str | None = None,
    register_id: str | None = None,
    relation: str | None = None,
) -> dict[str, Any]:
    """Build one owner entry. ``owner_type`` is ``person`` or ``company``."""
    return {
        "name": name,
        "type": owner_type,
        "relation": relation,
        "share_percent": share_percent,
        "share_band": share_band,
        "nominal_amount": nominal_amount,
        "currency": currency,
        "since": since,
        "register_id": register_id,
    }


def holding(
    *,
    name: str,
    country: str,
    register_id: str | None = None,
    share_percent: float | None = None,
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
    relation: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Build one holding or appointment entry for a company or person."""
    return {
        "name": name,
        "register_id": register_id,
        "country": country,
        "relation": relation,
        "share_percent": share_percent,
        "since": since,
        "until": until,
        "status": status,
        "source_url": source_url,
    }


def officer(*, name: str, role: str | None = None, since: str | None = None, officer_type: str = "person") -> dict[str, Any]:
    """Build one officer entry (managing director, board member, ...)."""
    return {"name": name, "type": officer_type, "role": role, "since": since}


def ownership_record(
    *,
    subject: dict[str, Any],
    provider: str,
    owners: list[dict[str, Any]] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    officers: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    limitation: str | None = None,
) -> dict[str, Any]:
    """Assemble the full normalized record and assert no private field leaked."""
    record = {
        "subject": subject,
        "owners": owners or [],
        "holdings": holdings or [],
        "officers": officers or [],
        "provider": provider,
        "warnings": warnings or [],
        "limitation": limitation,
    }
    leaked = _private_keys(record)
    if leaked:
        raise RegisterProviderError("provider_error", f"Private register fields were not removed: {sorted(leaked)}")
    return record


def _private_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {key for key in value if key in PRIVATE_PERSON_FIELDS}
        for item in value.values():
            found |= _private_keys(item)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found |= _private_keys(item)
        return found
    return set()


def to_float(value: Any) -> float | None:
    """Parse a number from register data; returns None for blanks."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
