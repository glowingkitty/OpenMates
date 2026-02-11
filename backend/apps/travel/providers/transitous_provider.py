"""
Transitous (MOTIS) transport provider stub for the travel app.

This provider will implement train, bus, and public transit connection search
via the MOTIS/Transitous API (https://api.transitous.org). Currently a stub
that returns empty results — full implementation planned for a future release.

Transitous endpoints to be used:
- /api/v3/plan: Multimodal routing (transit, walking, biking)
- /api/v1/geocode: City name / address geocoding
- /api/v1/stoptimes: Real-time departures from a stop
"""

import logging
from typing import List

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
)

logger = logging.getLogger(__name__)


class TransitousProvider(BaseTransportProvider):
    """
    Train/bus/public transit provider using the Transitous (MOTIS) API.

    Currently a stub — returns empty results with an info message.
    Will be fully implemented once the Transitous API integration is complete.
    """

    SUPPORTED_METHODS = {"train", "bus", "boat"}

    def __init__(self, base_url: str = "https://api.transitous.org") -> None:
        self.base_url = base_url

    def supports_transport_method(self, method: str) -> bool:
        return method in self.SUPPORTED_METHODS

    async def search_connections(
        self,
        legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
    ) -> List[ConnectionResult]:
        """
        Stub: train/bus/boat search is not yet implemented.

        Returns an empty list. Will be implemented with the Transitous MOTIS API
        (/api/v3/plan endpoint) to provide real public transit routing.
        """
        logger.info(
            "TransitousProvider.search_connections() called but not yet implemented. "
            f"Legs: {len(legs)}, passengers: {passengers}"
        )
        return []
