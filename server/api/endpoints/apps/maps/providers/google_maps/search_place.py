import googlemaps
import logging
import os
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_place_details(
        name:str,
        street:str,
        city:str,
        zip_code:str,
        api_key:str=os.getenv('APP_MAPS_PROVIDER_GOOGLE_MAPS_API_KEY')
    ) -> dict:
    """
    Fetches the place details from Google Maps API based on the provided name and address components.

    :param api_key: Your Google Maps API key.
    :param name: Name of the place (e.g., doctor's name).
    :param street: Street address of the place.
    :param city: City where the place is located.
    :param zip_code: ZIP code of the place.
    :return: A dictionary containing place details including ratings.
    """
    # Initialize the Google Maps client
    gmaps = googlemaps.Client(key=api_key)

    # Construct the full address
    address = f"{name}, {street}, {city}, {zip_code}"
    logger.info(f"Searching for place: {address}")

    # Perform a text search for the place
    try:
        results = gmaps.places(query=address)
        logger.debug(f"API response: {results}")

        if results['status'] == 'OK' and results['results']:
            # Get the first result
            place = results['results'][0]
            place_id = place['place_id']
            logger.info(f"Found place: {place['name']} with place_id: {place_id}")

            # Get detailed information about the place
            place_details = gmaps.place(place_id=place_id)

            if place_details['status'] == 'OK':
                details = place_details['result']
                return {
                    'name': details.get('name'),
                    'address': details.get('formatted_address'),
                    'rating': details.get('rating'),
                    'user_ratings_total': details.get('user_ratings_total')
                }
        else:
            logger.info("No results found for the given address.")
            return None
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None