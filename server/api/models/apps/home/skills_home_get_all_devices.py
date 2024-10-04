from typing import Optional, List
from pydantic import BaseModel, Field, model_validator
from typing import Literal

class Home(BaseModel):
    id: Optional[str] = Field(None, description="The id of the home")
    name: Optional[str] = Field(None, description="The name of the home")

    @model_validator(mode='after')
    def validate_home(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')
        return v

class Room(BaseModel):
    id: Optional[str] = Field(None, description="The id of the room")
    name: Optional[str] = Field(None, description="The name of the room")
    home: Home = Field(..., description="The home that the room belongs to")

    @model_validator(mode='after')
    def validate_room(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')
        return v

class HomeGetAllDevicesInput(BaseModel):
    home: Optional[Home] = Field(None, description="The home to get the devices from")
    rooms: Optional[List[Room]] = Field(None, description="The rooms for which to get the devices from")
    types: Optional[List[Literal[
        'light',
        'switch',
        'thermostat',
        'sensor'
    ]]] = Field(None, description="The types of the devices to get")

home_get_all_devices_input_example = {
    "home": {
        "id": "1",
        "name": "My Smart Home"
    },
    "types": ["light"]
}

class Device(BaseModel):
    id: str = Field(..., description="The id of the device")
    name: str = Field(..., description="The name of the device")
    type: Literal[
        'light',
        'switch',
        'thermostat',
        'sensor'
    ] = Field(..., description="The type of the device")
    description: Optional[str] = Field(None, description="The description of the device")
    room: Room = Field(..., description="The room that the device belongs to")

class HomeGetAllDevicesOutput(BaseModel):
    devices: List[Device] = Field(..., description="The list of devices in the home")

home_get_all_devices_output_example = {
    "devices": [
        {
            "id": "1234567890",
            "name": "Living Room LED lamp",
            "description": "A smart LED lamp in the living room.",
            "type": "light",
            "room": {
                "id": "1",
                "name": "Living Room",
                "home": {
                    "id": "1",
                    "name": "My Smart Home"
                }
            }
        },
        {
            "id": "1234567891",
            "name": "Bedroom LED lamp",
            "description": "A smart LED lamp in the bedroom.",
            "type": "light",
            "room": {
                "id": "2",
                "name": "Bedroom",
                "home": {
                    "id": "1",
                    "name": "My Smart Home"
                }
            }
        },
        {
            "id": "1234567892",
            "name": "Kitchen LED lamp",
            "description": "A smart LED lamp in the kitchen.",
            "type": "light",
            "room": {
                "id": "3",
                "name": "Kitchen",
                "home": {
                    "id": "1",
                    "name": "My Smart Home"
                }
            }
        }
    ]
}
