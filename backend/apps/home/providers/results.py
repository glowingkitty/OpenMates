"""Home provider results preserve partial failures separately from empty searches."""
from typing import Any


class ProviderListings(list[dict[str, Any]]):
    """A bounded listing page and warnings from failed detail requests."""

    def __init__(self, listings: list[dict[str, Any]], warnings: list[str] | None = None) -> None:
        super().__init__(listings)
        self.warnings = warnings or []
