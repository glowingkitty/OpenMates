import googlemaps
import logging
from datetime import datetime
import os
from typing import Union, Dict, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TODO add more filters
# TODO integrate to API

def search_connections(
        origin: Union[str, Tuple[float, float]],
        destination: Union[str, Tuple[float, float]],
        departure_time: datetime = None,
        api_key: str = os.getenv('APP_MAPS_PROVIDER_GOOGLE_MAPS_API_KEY')
    ) -> Dict:
    """
    Fetches top 3 transit connections between two locations using Google Maps Directions API.
    """
    # Initialize the Google Maps client
    logger.debug("Initializing Google Maps client")
    try:
        gmaps = googlemaps.Client(key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize Google Maps client: {e}")
        return None

    # Set departure time to now if not specified
    if departure_time is None:
        departure_time = datetime.now()

    logger.info(f"Calculating transit connections from {origin} to {destination}")

    try:
        # Request directions using transit mode with alternatives
        directions_result = gmaps.directions(
            origin,
            destination,
            mode="transit",
            departure_time=departure_time,
            alternatives=True
        )

        logger.debug(f"Received {len(directions_result)} alternative routes")

        if not directions_result:
            logger.info("No transit routes found")
            return None

        # Initialize result dictionary with connections array
        result = {
            'connections': []
        }

        # Process up to 3 alternative routes
        for route in directions_result[:3]:
            connection = {
                'duration': {
                    'text': route['legs'][0]['duration']['text'],
                    'minutes': route['legs'][0]['duration']['value'] // 60
                },
                'distance': {
                    'text': route['legs'][0]['distance']['text'],
                    'meters': route['legs'][0]['distance']['value']
                },
                'departure_time': route['legs'][0].get('departure_time', {}).get('text'),
                'arrival_time': route['legs'][0].get('arrival_time', {}).get('text'),
                'steps': []
            }

            # Extract step-by-step instructions
            for step in route['legs'][0]['steps']:
                step_info = {
                    'mode': step['travel_mode'],
                    'instruction': step['html_instructions'],
                    'duration': step['duration']['text']
                }

                # Add transit-specific details if available
                if step['travel_mode'] == 'TRANSIT':
                    transit_details = step['transit_details']
                    step_info.update({
                        'line': transit_details['line'].get('short_name', transit_details['line'].get('name')),
                        'departure_stop': transit_details['departure_stop']['name'],
                        'arrival_stop': transit_details['arrival_stop']['name'],
                        'num_stops': transit_details['num_stops']
                    })

                connection['steps'].append(step_info)

            result['connections'].append(connection)

        logger.info(f"Found {len(result['connections'])} alternative connections")
        return result

    except googlemaps.exceptions.ApiError as e:
        logger.error(f"Google Maps API error: {e}")
        return None
    except googlemaps.exceptions.TransportError as e:
        logger.error(f"Transport error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None