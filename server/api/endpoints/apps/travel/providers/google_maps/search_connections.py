import googlemaps
import logging
from datetime import datetime
import os
from typing import Union, Tuple, Optional, List
from server.api.models.apps.travel.skills_travel_search_connections import (
    Connection,
    Step,
    TransitDetails,
    TravelSearchConnectionsInput,
    TravelSearchConnectionsOutput
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def search_connections(
        input: TravelSearchConnectionsInput
    ) -> TravelSearchConnectionsOutput:
    """
    Fetches top 3 transit connections between two locations using Google Maps Directions API.
    Returns structured Connection objects with detailed transit information.
    """
    logger.debug("Processing search_connections request with input: %s", input)

    # Extract values from input model
    origin = input.origin
    destination = input.destination
    departure_time = datetime.fromisoformat(input.departure_time)

    try:
        gmaps = googlemaps.Client(key=os.getenv('APP_TRAVEL_PROVIDER_GOOGLE_MAPS_API_KEY'))
    except Exception as e:
        logger.error("Failed to initialize Google Maps client: %s", e)
        return TravelSearchConnectionsOutput(connections=[])

    logger.info("Calculating transit connections from %s to %s", origin, destination)

    try:
        directions_result = gmaps.directions(
            origin,
            destination,
            mode="transit",
            departure_time=departure_time,
            alternatives=True,
            transit_mode=['bus', 'subway', 'train', 'tram', 'rail']
        )

        logger.debug(f"Received {len(directions_result)} alternative routes")
        if not directions_result:
            logger.info("No transit routes found")
            return TravelSearchConnectionsOutput(connections=[])

        connections = []
        for route in directions_result[:3]:
            leg = route['legs'][0]

            # Process steps
            steps = []
            for step in leg['steps']:
                step_model = {
                    'travel_mode': step['travel_mode'],
                    'duration_minutes': step['duration']['value'] // 60,
                    'distance_meters': step['distance']['value'],
                    'instructions': step['html_instructions'],
                    'polyline': step['polyline']['points']
                }

                if step['travel_mode'] == 'TRANSIT':
                    transit = step['transit_details']
                    step_model['transit_details'] = TransitDetails(
                        line=transit['line'].get('short_name', transit['line'].get('name')),
                        vehicle_type=transit['line']['vehicle']['type'],
                        departure_stop=transit['departure_stop']['name'],
                        arrival_stop=transit['arrival_stop']['name'],
                        departure_time=transit['departure_time']['text'],
                        arrival_time=transit['arrival_time']['text'],
                        num_stops=transit['num_stops'],
                        headsign=transit['headsign'] if 'headsign' in transit else None
                    )

                steps.append(Step(**step_model))

            # Create Connection object
            connection = Connection(
                total_duration_minutes=leg['duration']['value'] // 60,
                total_distance_meters=leg['distance']['value'],
                departure_time=datetime.fromtimestamp(leg['departure_time']['value']),
                arrival_time=datetime.fromtimestamp(leg['arrival_time']['value']),
                steps=steps,
                polyline=route['overview_polyline']['points'],
                fare=route.get('fare', {}).get('value'),
                fare_currency=route.get('fare', {}).get('currency')
            )

            connections.append(connection)

        logger.info("Successfully processed %d connections", len(connections))
        return TravelSearchConnectionsOutput(connections=connections)

    except googlemaps.exceptions.ApiError as e:
        logger.error("Google Maps API error: %s", e)
        return TravelSearchConnectionsOutput(connections=[])
    except googlemaps.exceptions.TransportError as e:
        logger.error("Transport error: %s", e)
        return TravelSearchConnectionsOutput(connections=[])
    except Exception as e:
        logger.error("An unexpected error occurred: %s", e)
        return TravelSearchConnectionsOutput(connections=[])
