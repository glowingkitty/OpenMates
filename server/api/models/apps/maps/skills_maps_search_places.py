from pydantic import BaseModel, Field
from typing import Optional, List, Dict

class MapsSearchInput(BaseModel):
    """
    Input model for searching for places
    """
    query: str = Field(..., description="The query to search for")

maps_search_input_example = {
    "query": "Dr. Müller, Friedrichstraße 123, 10117, Berlin"
}

class Place(BaseModel):
    """
    A place found in the search
    """
    name: str = Field(..., description="The name of the place")
    address: str = Field(..., description="The address of the place")
    rating: Optional[float] = Field(None, description="The rating of the place")
    user_ratings_total: Optional[int] = Field(None, description="The number of user ratings")

class MapsSearchOutput(BaseModel):
    """
    Output model for searching for places
    """
    results: List[Place] = Field(..., description="The list of results")

maps_search_output_example = {
    "results": [
        {
            "name": "Dr. Müller",
            "address": "Friedrichstraße 123, 10117, Berlin",
            "rating": 4.5,
            "user_ratings_total": 32
        }
    ]
}

maps_search_output_task_example = {
    "id": "153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "team_slug": "openmatesdevs",
    "url": "/v1/openmatesdevs/tasks/153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "api_endpoint": "/v1/openmatesdevs/apps/maps/search_places",
    "title": "Search for places",
    "status": "scheduled",
    "progress": 0,
    "time_scheduled_for": None,
    "time_started": "2023-05-17T12:34:56.789Z",
    "time_estimated_completion": "2023-05-17T12:36:00.000Z",
    "time_completion": None,
    "execution_time_seconds": None,
    "total_credits_cost_estimated": 720,
    "total_credits_cost_real": None,
    "output": None,
    "error": None
}