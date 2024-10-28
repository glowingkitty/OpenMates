from server.api.models.apps.travel.skills_travel_search_connections import TravelSearchConnectionsInput, TravelSearchConnectionsOutput
from server.api.endpoints.apps.travel.providers.google_maps.search_connections import search_connections as search_connections_google_maps


def search_connections(
        input: TravelSearchConnectionsInput
    ) -> TravelSearchConnectionsOutput:
    """
    Search for travel connections
    """
    if input.provider.name == "google_maps":
        return search_connections_google_maps(input)
    else:
        raise ValueError(f"Provider {input.provider.name} not supported")
