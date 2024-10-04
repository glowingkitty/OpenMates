from pydantic import BaseModel


class HomeGetTemperatureInput(BaseModel):
    device_id: str


class HomeGetTemperatureOutput(BaseModel):
    temperature: float
