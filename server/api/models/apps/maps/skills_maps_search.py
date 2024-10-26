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