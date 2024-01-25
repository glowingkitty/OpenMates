import requests

# doesn't seem to work yet. Not sure if station down or other reason. Last checked: Oct 14 2023

def get_weather(station_id):
    response = requests.get(f'https://dwd.api.proxy.bund.dev/v30/stationOverviewExtended/{station_id}')
    return response.json()

def rain_forecast(station_id):
    data = get_weather(station_id)
    print(data)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    # Load .env file
    load_dotenv()
    # Get the API key and lat/lon from the .env file
    station_id = os.getenv('DEUTSCHERWETTERDIENST_STATION_ID')
    rain_forecast(station_id)