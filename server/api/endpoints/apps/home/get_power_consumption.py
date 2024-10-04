from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_get_power_consumption import (
    HomeGetPowerConsumptionInput,
    HomeGetPowerConsumptionOutput,
    PowerConsumption
)

logger = logging.getLogger(__name__)


async def get_power_consumption(
    team_slug: str,
    api_token: str,
    input: HomeGetPowerConsumptionInput
) -> HomeGetPowerConsumptionOutput:
    try:
        logger.debug("Getting power consumption")

        # TODO add processing via MQTT

        today_power_consumption = PowerConsumption(kwh=0)
        yesterday_power_consumption = PowerConsumption(kwh=0)
        this_week_power_consumption = PowerConsumption(kwh=0)
        last_week_power_consumption = PowerConsumption(kwh=0)
        this_month_power_consumption = PowerConsumption(kwh=0)
        last_month_power_consumption = PowerConsumption(kwh=0)
        this_year_power_consumption = PowerConsumption(kwh=0)
        last_year_power_consumption = PowerConsumption(kwh=0)
        all_time_power_consumption = PowerConsumption(kwh=0)
        recording_start_power_consumption = "2024-02-29T12:00:00Z"

        logger.debug("Got power consumption")
        return HomeGetPowerConsumptionOutput(
            today=today_power_consumption,
            yesterday=yesterday_power_consumption,
            this_week=this_week_power_consumption,
            last_week=last_week_power_consumption,
            this_month=this_month_power_consumption,
            last_month=last_month_power_consumption,
            this_year=this_year_power_consumption,
            last_year=last_year_power_consumption,
            all_time=all_time_power_consumption,
            recording_start=recording_start_power_consumption
        )
    except Exception:
        logger.exception("Error getting power consumption")
        raise HTTPException(status_code=500, detail="An error occurred while getting power consumption")
