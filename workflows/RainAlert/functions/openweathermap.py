

import requests
import datetime

def get_weather_openweather(api_key, lat, lon):
    response = requests.get(f'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&appid={api_key}')
    return response.json()

def get_rain_forecast_openweather(api_key, lat, lon):
    data = get_weather_openweather(api_key, lat, lon)
    rain_hours = []
    for hour in data['hourly'][:6]:
        if 'rain' in hour:
            rain_hours.append(datetime.datetime.fromtimestamp(hour['dt']).hour)
    if rain_hours:
        rain_hours.sort()
        rain_start = rain_hours[0]
        rain_end = rain_hours[-1] + 1  # add 1 to get the end of the hour
        print(f"There will be rain between {rain_start}:00 to {rain_end}:00. To skip the rain, go out before or after that.")
    else:
        print("No rain.")



if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    # Load .env file
    load_dotenv()
    # Get the API key and lat/lon from the .env file
    api_key = os.getenv('OPENWEATHERMAP_API_LEY')
    lat = os.getenv('LOCATION_LAT')
    lon = os.getenv('LOCATION_LON')

    get_rain_forecast_openweather(api_key, lat, lon)
