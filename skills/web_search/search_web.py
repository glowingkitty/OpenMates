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

def search_web(keywords: str, max_results: int = 10) -> list:
    try:
        add_to_log(module_name="Web Search", color="yellow", state="start")
        add_to_log(f"Searching for web results on DuckDuckGo with the keywords: {keywords}")

        results = []
        
        with DDGS() as ddgs:
            for result in ddgs.text(
                keywords, 
                region='wt-wt', 
                safesearch='off', 
                timelimit='y',
                max_results=max_results
                ):
                results.append(result)

        add_to_log(f"Found {len(results)} web results on DuckDuckGo for '{keywords}'")
        return results

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to search for web results on DuckDuckGo for '{keywords}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    results = search_web("Apple Vision Pro")
    with open('results.json', 'w') as f:
        json.dump(results, f, indent=4)
    subprocess.run(["code", "results.json"])