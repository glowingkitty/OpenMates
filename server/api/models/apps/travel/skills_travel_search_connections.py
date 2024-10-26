from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class TravelSearchConnectionsInput(BaseModel):
    """
    Input model for searching for connections
    """
    origin: str = Field(..., description="The origin of the connection")
    destination: str = Field(..., description="The destination of the connection")
    departure_time: str = Field(..., description="The departure time of the connection in ISO 8601 format")

travel_search_connections_input_example = {
    "origin": "Friedrichstraße 123, 10117, Berlin",
    "destination": "Marienplatz, 80331, München",
    "departure_time": "2024-10-26T10:00:00"
}


class TransitDetails(BaseModel):
    """
    Model representing transit-specific details
    """
    line: str = Field(..., description="Transit line identifier")
    vehicle_type: str = Field(..., description="Type of transit vehicle (BUS, SUBWAY, etc.)")
    departure_stop: str = Field(..., description="Name of departure stop")
    arrival_stop: str = Field(..., description="Name of arrival stop")
    departure_time: str = Field(..., description="Scheduled departure time")
    arrival_time: str = Field(..., description="Scheduled arrival time")
    num_stops: int = Field(..., description="Number of stops in this transit segment")
    headsign: Optional[str] = Field(None, description="Headsign of the transit vehicle")

class Step(BaseModel):
    """
    Model representing a single step in the journey
    """
    travel_mode: str = Field(..., description="Mode of travel (TRANSIT, WALKING, etc.)")
    duration_minutes: int = Field(..., description="Duration of step in minutes")
    distance_meters: int = Field(..., description="Distance of step in meters")
    instructions: str = Field(..., description="Human-readable instructions")
    transit_details: Optional[TransitDetails] = Field(None, description="Transit-specific details if travel_mode is TRANSIT")
    polyline: str = Field(..., description="Encoded polyline for this step")

class Connection(BaseModel):
    """
    Model representing a complete transit connection
    """
    total_duration_minutes: int = Field(..., description="Total journey duration in minutes")
    total_distance_meters: int = Field(..., description="Total journey distance in meters")
    departure_time: datetime = Field(..., description="Scheduled departure time")
    arrival_time: datetime = Field(..., description="Scheduled arrival time")
    steps: List[Step] = Field(..., description="List of journey steps")
    fare: Optional[float] = Field(None, description="Fare amount if available")
    fare_currency: Optional[str] = Field(None, description="Currency of the fare")
    polyline: str = Field(..., description="Encoded polyline for entire route")

class TravelSearchConnectionsOutput(BaseModel):
    """
    Output model for searching for connections
    """
    connections: List[Connection] = Field(..., description="The list of connections")

travel_search_connections_output_example = {
    "connections": [
        {
            "total_duration_minutes": 120,
            "total_distance_meters": 10000,
        }
    ]
}