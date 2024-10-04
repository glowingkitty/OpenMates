from pydantic import BaseModel

class HomeGetPowerConsumptionInput(BaseModel):
    device_id: str


class HomeGetPowerConsumptionOutput(BaseModel):
    power_consumption: float
