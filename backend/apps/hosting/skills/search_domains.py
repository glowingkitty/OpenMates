"""Search schemas and explicit unavailable capability boundary."""

from __future__ import annotations


import re


from typing import Any, Literal


from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.apps.base_skill import BaseSkill

from backend.shared.python_utils.search_relevance import (
    normalize_relevance_criteria,
)


MAX_CHECKED = 40

GROUP_DEADLINE_SECONDS = 40

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

_COUNTRY = re.compile(r"^[A-Z]{2}$")

_ISO_COUNTRIES = frozenset(
    (
        "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL "
        "BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU "
        "CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA "
        "GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID "
        "IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB "
        "LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT "
        "MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL "
        "PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN "
        "SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG "
        "UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
    ).split()
)


def _domain(value: str) -> tuple[str, str]:
    """Validate a complete DNS name locally, including Unicode/IDNA labels."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 253
        or value != value.strip()
    ):
        raise ValueError("Invalid domain name")
    raw = value.rstrip(".").lower()
    if "." not in raw:
        raise ValueError("A full domain name is required")
    try:
        ascii_name = raw.encode("idna").decode("ascii")
        if len(ascii_name) > 253 or any(
            not _LABEL.fullmatch(label) for label in ascii_name.split(".")
        ):
            raise ValueError("Invalid domain name")
        return ascii_name, ascii_name.encode("ascii").decode("idna")
    except UnicodeError as exc:
        raise ValueError("Invalid domain name") from exc


def _short_name(value: str) -> str:
    try:
        ascii_name = value.lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid domain name") from exc
    if not _LABEL.fullmatch(ascii_name):
        raise ValueError("Invalid domain name")
    return ascii_name


def _tld(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid TLD")
    raw = value.strip().lstrip(".").lower()
    if not raw or len(raw) > 100:
        raise ValueError("Invalid TLD")
    ascii_name, _ = _domain("test." + raw)
    suffix = ascii_name[5:]
    if not all(_LABEL.fullmatch(label) for label in suffix.split(".")):
        raise ValueError("Invalid TLD")
    return suffix


class DomainSearchRequestItem(BaseModel):
    """One independent exact check or bounded discovery request."""

    model_config = ConfigDict(extra="forbid")

    id: str | int | None = None
    query: str
    tlds: list[str] | None = Field(default=None, max_length=5)
    country: str = "DE"
    currency: str = "EUR"
    max_results: int = Field(default=10, ge=1, le=20, strict=True)
    availability: Literal["prefer_available", "available_only", "all"] = (
        "prefer_available"
    )
    relevance_criteria: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def valid_id(cls, value: str | int | None) -> str | int | None:
        if isinstance(value, bool):
            raise ValueError("Invalid request ID")
        return value

    @field_validator("query")
    @classmethod
    def valid_query(cls, value: str) -> str:
        query = value.strip()
        if not query or any(ord(char) < 32 for char in query):
            raise ValueError("Invalid search query")
        if "." in query:
            if len(query) > 253:
                raise ValueError("Invalid domain name")
            _domain(query)
        else:
            if len(query) > 100:
                raise ValueError("Invalid search query")
            if " " not in query:
                _short_name(query)
        return query

    @field_validator("tlds")
    @classmethod
    def valid_tlds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(_tld(item) for item in value))

    @field_validator("country")
    @classmethod
    def valid_country(cls, value: str) -> str:
        value = value.upper()
        if not _COUNTRY.fullmatch(value) or value not in _ISO_COUNTRIES:
            raise ValueError("Invalid country code")
        return value

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        value = value.upper()
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency")
        return value

    @field_validator("relevance_criteria")
    @classmethod
    def valid_criteria(cls, value: str | None) -> str | None:
        return normalize_relevance_criteria(value)


class DomainSearchRequest(BaseModel):
    """Grouped requests; raw children permit independent validation errors."""

    requests: list[Any] = Field(min_length=1, max_length=5)


class DomainSearchResponse(BaseModel):
    """Groups preserve selection, checked evidence, and safe failure status."""

    success: bool = False
    app_id: str = "hosting"
    skill_id: str = "search_domains"
    provider: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None


SUPPORTED_CURRENCIES = frozenset({"EUR", "USD"})


class SearchDomainsSkill(BaseSkill):
    """Preserve the capability path while no permitted provider is configured."""

    async def execute(self, *args: Any, **kwargs: Any):
        return DomainSearchResponse(
            error="No permitted provider is available for this capability.",
            error_code="provider_unavailable",
        )
