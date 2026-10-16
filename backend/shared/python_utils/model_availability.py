"""Date-based availability for explicitly marked legacy chat models."""

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Mapping


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _configured_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.isoformat() == value else None
    return None


def is_model_available(model: Mapping[str, Any], *, today: date | None = None) -> bool:
    """Limit marked legacy ai.ask models to their recent, unretired API window.

    Curated models are unaffected. A legacy model with missing or invalid date
    metadata fails closed so a stale catalogue cannot advertise it as routable.
    """
    if model.get("for_app_skill") != "ai.ask" or model.get("legacy_model") is not True:
        return True

    current = today or utc_today()
    oldest_day = date(
        current.year - 1,
        current.month,
        min(current.day, monthrange(current.year - 1, current.month)[1]),
    )
    released = _configured_date(model.get("release_date"))
    if released is None or not oldest_day <= released <= current:
        return False

    retirement_value = model.get("api_retirement_date")
    if retirement_value is None:
        return True
    retirement = _configured_date(retirement_value)
    return retirement is not None and retirement > current
