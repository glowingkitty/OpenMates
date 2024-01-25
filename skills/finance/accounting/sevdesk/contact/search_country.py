################

# Default Imports

################
import sys
import os
import re
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.accounting.sevdesk.contact.get_countries import get_countries

# country_code -> ISO 3166-1 alpha-2

def search_country(country_code: str) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Search country in SevDesk ...")

        all_countries = get_countries()

        # search for the country
        for country in all_countries:
            if country["code"].lower() == country_code.lower():
                add_to_log(f"Found the country: {country['name']}", state="success")
                return country
        
        process_error(f"Failed to find country (code: {country_code}).")
        return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to find country.", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    country = search_country(country_code="de")
    print("ID:")
    print(country["id"])