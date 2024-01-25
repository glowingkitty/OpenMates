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

def search_news(keywords: str, max_results: int = 10) -> list:
    try:
        add_to_log(module_name="News Search", color="yellow", state="start")
        add_to_log(f"Searching for news on DuckDuckGo with the keywords: {keywords}")

        results = []
        
        with DDGS() as ddgs:
            ddgs_news_gen = ddgs.news(
            keywords,
            region="wt-wt",
            safesearch="off",
            timelimit="m",
            max_results=max_results
            )
            for result in ddgs_news_gen:
                results.append(result)
            

        add_to_log(f"Found {len(results)} news results on DuckDuckGo for '{keywords}'")
        return results

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to search for news on DuckDuckGo for '{keywords}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    news_results = search_news("Apple Vision Pro")
    with open('news_results.json', 'w') as f:
        json.dump(news_results, f, indent=4)
    subprocess.run(["code", "news_results.json"])