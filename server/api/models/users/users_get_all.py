from pydantic import BaseModel, Field
from typing import List, Dict
from server.api.models.metadata import MetaData


# GET /users (get all users for a team)

class UserMini(BaseModel):
    """This is the model for a single user, for the endpoint GET /users"""
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")

    @classmethod
    def from_redis_dict(cls, data: Dict[str, str]) -> 'UserMini':
        """Create a UserMini object from Redis data."""
        return cls(
            id=int(data['id']),
            username=data['username']
        )

class UsersGetAllOutput(BaseModel):
    data: List[UserMini] = Field(..., description="List of all users")
    meta: MetaData = Field(..., description="Metadata for the response")


users_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "username": "johnd"
        },
        {
            "id": 2,
            "username": "janea"
        }
    ],
    "meta": {
        "pagination": {
            "page": 1,
            "pageSize": 25,
            "pageCount": 1,
            "total": 2
        }
    }
}