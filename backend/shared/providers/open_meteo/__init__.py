# backend/shared/providers/open_meteo/__init__.py
#
# Open-Meteo provider package.
# Provides no-key global geocoding and forecast fallback data.
# Provider functions stay app-agnostic so weather skills can reuse them.
#
# Documentation: https://open-meteo.com/

from .open_meteo import geocode_location, fetch_forecast, normalize_forecast_days

__all__ = ["geocode_location", "fetch_forecast", "normalize_forecast_days"]
