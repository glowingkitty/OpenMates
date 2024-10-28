import googlemaps
import logging
import os
from server.api.models.apps.maps.skills_maps_search import MapsSearchInput, MapsSearchOutput, Place

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def search_places(
        input: MapsSearchInput
    ) -> MapsSearchOutput:
    """
    Fetches the places details from Google Maps API based on the provided query string.

    :param input: MapsSearchInput object containing the search query
    :return: MapsSearchOutput object containing a list of found places
    """
    # Initialize the Google Maps client
    gmaps = googlemaps.Client(key=os.getenv('APP_MAPS_PROVIDER_GOOGLE_MAPS_API_KEY'))

    logger.info(f"Searching for places with query: {input.query}")

    # Perform a text search for the place
    try:
        results = gmaps.places(query=input.query)
        logger.debug(f"API response: {results}")

        if results['status'] == 'OK' and results['results']:
            places_list = []
            # Process all results
            for place in results['results']:
                place_id = place['place_id']
                logger.info(f"Found place: {place['name']} with place_id: {place_id}")

                # Get detailed information about the place
                # TODO: check if details are even requested, else skip
                place_details = gmaps.place(place_id=place_id)

                if place_details['status'] == 'OK':
                    details = place_details['result']
                    places_list.append(Place(
                        name=details.get('name'),
                        address=details.get('formatted_address'),
                        rating=details.get('rating'),
                        user_ratings_total=details.get('user_ratings_total')
                    ))

            return MapsSearchOutput(results=places_list)

        logger.info("No results found for the given query.")
        return MapsSearchOutput(results=[])

    except Exception as e:
        logger.error(f"An error occurred while searching for places: {e}")
        raise  # Let the API handler deal with the error
