from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class Device(BaseModel):
    """
    The device details.

    Attributes:
        id (str): The id of the device.
        name (str): The name of the device.
    """
    id: Optional[str] = Field(None, description="The id of the device")
    name: Optional[str] = Field(None, description="The name of the device")

    @model_validator(mode='after')
    def validate_device(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')
        return v

class Home(BaseModel):
    """
    The home details.

    Attributes:
        id (str): The id of the home.
        name (str): The name of the home.
    """
    id: Optional[str] = Field(None, description="The id of the home")
    name: Optional[str] = Field(None, description="The name of the home")

    @model_validator(mode='after')
    def validate_home(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')
        return v

class Room(BaseModel):
    """
    The room details.

    Attributes:
        id (str): The id of the room.
        name (str): The name of the room.
    """
    id: Optional[str] = Field(None, description="The id of the room")
    name: Optional[str] = Field(None, description="The name of the room")
    home: Optional[Home] = Field(None, description="The home that the room belongs to")

    @model_validator(mode='after')
    def validate_room(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')


class HomeGetTemperatureInput(BaseModel):
    """
    The input of the home get temperature skill.

    Attributes:
        devices (List[Device]): The sensors to get the temperature from.
        rooms (List[Room]): The rooms to get the temperature from.
        home (Home): The home to get the temperature from.
    """
    devices: Optional[List[Device]] = Field(None, description="The sensors to get the temperature from")
    rooms: Optional[List[Room]] = Field(None, description="The rooms to get the temperature from")
    home: Optional[Home] = Field(None, description="The home to get the temperature from")

    @model_validator(mode='after')
    def validate_home_get_temperature_input(cls, v):
        if v.devices is None and v.rooms is None and v.home is None:
            raise ValueError('Either devices, rooms, or home must be provided')
        return v

home_get_temperature_input_example = {
    "home": {
        "name": "My Smart Home"
    }
}


class Temperature(BaseModel):
    """
    The temperature details.

    Attributes:
        device (Device): The device that the temperature is from.
        room (Room): The room that the temperature is from.
        celsius (float): The temperature in degrees Celsius.
        fahrenheit (float): The temperature in degrees Fahrenheit.
        humidity (float): The humidity in percent.
    """
    device: Device = Field(..., description="The device that the temperature is from")
    room: Room = Field(..., description="The room that the temperature is from")
    celsius: float = Field(..., description="The temperature in degrees Celsius")
    fahrenheit: float = Field(..., description="The temperature in degrees Fahrenheit")
    humidity: float = Field(..., description="The humidity in percent")

class HomeGetTemperatureOutput(BaseModel):
    """
    The output of the home get temperature skill.

    Attributes:
        temperatures (List[Temperature]): The temperatures from the devices.
    """
    temperatures: List[Temperature] = Field(..., description="The temperatures from the devices")

home_get_temperature_output_example = {
    "temperatures": [
        {
            "device": {
                "id": "1234567894",
                "name": "Living Room Temperature Sensor"
            },
            "room": {
                "id": "1",
                "name": "Living Room",
                "home": {
                    "id": "1",
                    "name": "My Smart Home"
                }
            },
            "celsius": 22.5,
            "fahrenheit": 72.7,
            "humidity": 55.2
        },
        {
            "device": {
                "id": "1234567895",
                "name": "Bedroom Temperature Sensor"
            },
            "room": {
                "id": "2",
                "name": "Bedroom",
                "home": {
                    "id": "1",
                    "name": "My Smart Home"
                }
            },
            "celsius": 21.2,
            "fahrenheit": 70.1,
            "humidity": 50.1
        }
    ]
}