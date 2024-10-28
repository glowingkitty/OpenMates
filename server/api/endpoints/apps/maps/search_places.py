from server.api.models.apps.maps.skills_maps_search_places import MapsSearchInput, MapsSearchOutput
from server.api.endpoints.apps.maps.providers.google_maps.search_places import search_places as search_places_google_maps


def search_places(
        input: MapsSearchInput
    ) -> MapsSearchOutput:
    """
    Search for doctors
    """
    if input.provider.name == "google_maps":
        return search_places_google_maps(input)
    else:
        raise ValueError(f"Provider {input.provider.name} not supported")
