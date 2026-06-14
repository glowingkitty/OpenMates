# backend/shared/providers/bright_sky/__init__.py
#
# Bright Sky provider package.
# Exposes JSON access to DWD-based weather forecast and radar data.
# Provider functions stay app-agnostic so weather skills can reuse them.
#
# Documentation: https://brightsky.dev/docs/

from .bright_sky import fetch_radar, fetch_weather, normalize_radar_frames, normalize_weather_days

__all__ = ["fetch_radar", "fetch_weather", "normalize_radar_frames", "normalize_weather_days"]
