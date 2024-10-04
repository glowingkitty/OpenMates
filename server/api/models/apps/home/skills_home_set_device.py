from pydantic import BaseModel, Field
from typing import Literal
from pydantic import model_validator
import re

class Command(BaseModel):
    """
    The command details.

    Attributes:
        state (Literal['power', 'brightness', 'color', 'effect', 'temperature_celsius', 'temperature_fahrenheit']): The state to set.
        value (str): The value to set the state to.
    """
    state: Literal[
        'power',
        'brightness',
        'color',
        'effect',
        'temperature_celsius',
        'temperature_fahrenheit'
    ] = Field(..., description="Which state should be set?")
    value: str = Field(..., description="What should the state be set to?")

    @model_validator(mode='after')
    def validate_state(self):
        """
        Validate the state and value.
        """
        if self.state == 'power':
            if self.value not in ['on', 'off']:
                raise ValueError("Invalid power value")
        elif self.state == 'brightness':
            if not self.value.isdigit():
                raise ValueError("Brightness value must be a number")
            if int(self.value) < 0 or int(self.value) > 100:
                raise ValueError("Brightness value must be between 0 and 100")
        elif self.state == 'color':
            if not re.match(r'^#[0-9A-Fa-f]{6}$', self.value):
                raise ValueError("Color value must be a valid hexadecimal color code (e.g., #FF00FF)")
        elif self.state == 'temperature_celsius':
            if not self.value.isdigit():
                raise ValueError("Temperature value must be a number")
            if float(self.value) < 10 or float(self.value) > 30:
                raise ValueError("Temperature value must be between 10 and 30 degrees Celsius")
        elif self.state == 'temperature_fahrenheit':
            if not self.value.isdigit():
                raise ValueError("Temperature value must be a number")
            if float(self.value) < 50 or float(self.value) > 86:
                raise ValueError("Temperature value must be between 50 and 86 degrees Fahrenheit")
        return self

class HomeSetDeviceInput(BaseModel):
    """
    The input of the home set device skill.

    Attributes:
        id (str): The id of the device to set.
        command (Command): The command to send to the device.
    """
    id: str = Field(..., description="What is the id of the device to set?")
    command: Command = Field(..., description="What command should be sent to the device?")

home_set_device_input_example = {
    "id": "1234567890",
    "command": {
        "state": "power",
        "value": "on"
    }
}

class HomeSetDeviceOutput(BaseModel):
    """
    The output of the home set device skill.

    Attributes:
        success (bool): Whether the device was set successfully.
    """
    success: bool = Field(..., description="Was the request sent successfully?")

home_set_device_output_example = {
    "success": True
}