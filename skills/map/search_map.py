################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from duckduckgo_search import DDGS

def search_map(keywords: str, place: str, max_results: int = 10) -> list:
    try:
        add_to_log(module_name="Map Search", color="yellow", state="start")
        add_to_log(f"Searching for map places on DuckDuckGo with the keywords: {keywords}")

        results = []
        
        with DDGS() as ddgs:
            for result in ddgs.maps(
                keywords,
                place=place,
                max_results=max_results
                ):
                results.append(result)

        add_to_log(f"Found {len(results)} map results on DuckDuckGo for '{keywords}'")
        return results

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to search for map places on DuckDuckGo for '{keywords}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    map_results = search_map("Falafel", "10997 Berlin")
    with open('map_results.json', 'w') as f:
        json.dump(map_results, f, indent=4)
    subprocess.run(["code", "map_results.json"])