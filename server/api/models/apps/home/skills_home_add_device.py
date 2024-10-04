from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from pydantic import model_validator


class Home(BaseModel):
    """
    The home details of the device.

    Attributes:
        id (str): The id of the home.
        name (str): The name of the home.
        description (str): The description of the home.
    """
    id: str = Field(..., description="The id of the home")
    name: str = Field(..., description="The name of the home")
    description: Optional[str] = Field(None, description="The description of the home")

class Room(BaseModel):
    """
    The room details of the device.

    Attributes:
        id (str): The id of the room.
        name (str): The name of the room.
        description (str): The description of the room.
        home (Home): The home that the room belongs to.
    """
    id: str = Field(..., description="The id of the room")
    name: str = Field(..., description="The name of the room")
    description: Optional[str] = Field(None, description="The description of the room")
    home: Home = Field(..., description="The home that the room belongs to")

class MQTTTopic(BaseModel):
    """
    The MQTT topic details of the device.

    Attributes:
        state (str): The state of the device this topic is for.
        description (str): The description of the topic.
        topic_path (str): The topic path.
    """
    state: Literal[
        'power',
        'brightness',
        'color',
        'effect',
        'temperature_celsius',
        'temperature_fahrenheit'
    ] = Field(..., description="The state of the device this topic is for")
    description: Optional[str] = Field(None, description="The description of the topic")
    topic_path: str = Field(..., description="The topic path")
    is_command: bool = Field(default=False, description="Whether this is a command topic")
    is_status: bool = Field(default=False, description="Whether this is a status topic")

    @model_validator(mode='after')
    def check_is_command_or_is_status(cls, v):
        if v.is_command and v.is_status:
            raise ValueError('An MQTT topic must be either a command or status topic, but not both.')
        return v

class MQTT(BaseModel):
    """
    The MQTT details of the device.

    Attributes:
        client_id (str): The client ID for the MQTT connection.
        topics (List[MQTTTopic]): A list of topics for different device settings.
    """
    client_id: Optional[str] = Field(None, description="The client ID for the MQTT connection")
    topics: List[MQTTTopic] = Field(..., description="A list of topics for different device settings")

    @model_validator(mode='after')
    def validate_mqtt_topics(cls, v):
        topic_states = set(topic.state for topic in v.topics)
        if 'power' not in topic_states:
            raise ValueError('A topic for the "power" state is required')
        return v

class HomeAddDeviceInput(BaseModel):
    """
    The input of the home add device skill.

    Attributes:
        id (str): The id of the device.
        name (str): The name of the device.
        type (str): The type of the device.
        description (str): The description of the device.
        room (Room): The room to add the device to.
        mqtt (MQTT): The MQTT details of the device.
    """
    id: str = Field(..., description="The id of the device")
    name: str = Field(..., description="The name of the device")
    type: Literal[
        'light',
        'switch',
        'thermostat',
        'sensor'
    ] = Field(..., description="The type of the device")
    description: Optional[str] = Field(None, description="The description of the device")
    room: Room = Field(..., description="The room to add the device to")
    mqtt: MQTT = Field(..., description="The MQTT details of the device")

home_add_device_input_example = {
    "id": "1234567890",
    "name": "Living Room LED lamp",
    "type": "light",
    "description": "A smart LED lamp in the living room.",
    "room": {
        "id": "1",
        "name": "Living Room",
        "description": "The main living area.",
        "home": {
            "id": "1",
            "name": "My Smart Home",
            "description": "My fully automated home."
        }
    },
    "mqtt": {
        "client_id": "led_lamp_living_room",
        "topics": [
            {
                "state": "power",
                "is_status": True,
                "is_command": False,
                "description": "Get the power state of the LED lamp",
                "topic_path": "led_lamp/living_room/power"
            },
            {
                "state": "power",
                "is_status": False,
                "is_command": True,
                "description": "Set the power state of the LED lamp",
                "topic_path": "led_lamp/living_room/power/set"
            },
            {
                "state": "brightness",
                "is_status": True,
                "is_command": False,
                "description": "Get the brightness of the LED lamp",
                "topic_path": "led_lamp/living_room/brightness"
            },
            {
                "state": "brightness",
                "is_status": False,
                "is_command": True,
                "description": "Set the brightness of the LED lamp",
                "topic_path": "led_lamp/living_room/brightness/set"
            }
        ]
    }
}

class HomeAddDeviceOutput(BaseModel):
    """
    The output of the home add device skill.

    Attributes:
        success (bool): Whether the device was added successfully.
    """
    success: bool

home_add_device_output_example = {
    "success": True
}