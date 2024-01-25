################

# Default Imports

################
import sys
import os
import re
import requests
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

def get_countries() -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Retrieving countries from SevDesk ...")

        file_path = os.path.join(os.path.dirname(__file__), 'countries.json')
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                add_to_log(f"Found a json file with the countries. Returning it. File: {file_path}.", state="success", module_name="SevDesk")
                return json.load(f)
        
        # Replace with your actual SevDesk API key
        secrets = load_secrets()
        api_key = secrets.get("SEVDESK_API_KEY")
        headers = {
            'Authorization': api_key
        }
        parameters = {}
        url = 'https://my.sevdesk.de/api/v1/StaticCountry'
        
        offset = 0
        all_countries = []
        while True:
            parameters['offset'] = offset
            response = requests.get(url, headers=headers, params=parameters)
            if response.status_code == 200:
                new_countries = response.json()["objects"]
                all_countries.extend(new_countries)
                
                if len(new_countries) < 100:
                    break
                offset += 100
            else:
                process_error(f"Failed to retrieve countries, status code: {response.status_code}")
                break
        
        # save the countries to a file
        with open(file_path, "w") as f:
            json.dump(all_countries, f, indent=4)
        
        add_to_log(f"Successfully retrieved all countries. Saved them to {file_path}.", state="success")
        return all_countries
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get countries from SevDesk API", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    get_countries()