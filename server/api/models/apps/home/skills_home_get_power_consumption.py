from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import datetime
class Device(BaseModel):
    id: Optional[str] = Field(None, description="The id of the device")
    name: Optional[str] = Field(None, description="The name of the device")

    @model_validator(mode='after')
    def validate_device(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')
        return v

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
    home: Optional[Home] = Field(None, description="The home that the room belongs to")

    @model_validator(mode='after')
    def validate_room(cls, v):
        if v.id is None and v.name is None:
            raise ValueError('Either id or name must be provided')


class HomeGetPowerConsumptionInput(BaseModel):
    devices: Optional[List[Device]] = Field(None, description="The devices to get the power consumption for")
    rooms: Optional[List[Room]] = Field(None, description="The rooms to get the power consumption for")
    home: Optional[Home] = Field(None, description="The home to get the power consumption for")

    @model_validator(mode='after')
    def validate_home_get_power_consumption_input(cls, v):
        if v.devices is None and v.rooms is None and v.home is None:
            raise ValueError('Either devices, rooms, or home must be provided')
        return v

home_get_power_consumption_input_example = {
    "devices": [
        {
            "id": "1234567890",
            "name": "Living Room LED lamp"
        }
    ]
}


class PowerConsumption(BaseModel):
    kwh: float = Field(..., description="The power consumption in kWh")

class HomeGetPowerConsumptionOutput(BaseModel):
    today: PowerConsumption = Field(..., description="The power consumption for today")
    yesterday: PowerConsumption = Field(..., description="The power consumption for yesterday")
    last_week: PowerConsumption = Field(..., description="The power consumption for the last week")
    last_month: PowerConsumption = Field(..., description="The power consumption for the last month")
    last_year: PowerConsumption = Field(..., description="The power consumption for the last year")
    all_time: PowerConsumption = Field(..., description="The power consumption for all time")
    recording_start: str = Field(..., description="The start date and time of the power consumption recording, in ISO 8601 format")

    @model_validator(mode='after')
    def validate_recording_start(cls, v):
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError('The recording start date and time must be in ISO 8601 format')
        return v

home_get_power_consumption_output_example = {
    "today": {
        "kwh": 0.48  # Assuming 8 hours of use at 60W
    },
    "yesterday": {
        "kwh": 0.42  # Slightly less usage than today
    },
    "last_week": {
        "kwh": 3.36  # Average daily consumption * 7 days
    },
    "last_month": {
        "kwh": 14.4  # Average daily consumption * 30 days
    },
    "last_year": {
        "kwh": 175.2  # Average daily consumption * 365 days
    },
    "all_time": {
        "kwh": 350.4  # Assuming 2 years of usage
    },
    "recording_start": "2022-01-09T13:21:45Z"
}