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

def search_videos(keywords: str, max_results: int = 10) -> list:
    try:
        add_to_log(module_name="Videos Search", color="yellow", state="start")
        add_to_log(f"Searching for videos on DuckDuckGo with the keywords: {keywords}")

        results = []
        
        with DDGS() as ddgs:
            ddgs_videos_gen = ddgs.videos(
            keywords,
            region="wt-wt",
            safesearch="off",
            # timelimit="w",
            # resolution="high",
            # duration="medium",
            max_results=max_results
            )
            for result in ddgs_videos_gen:
                results.append(result)
            

        add_to_log(f"Found {len(results)} videos on DuckDuckGo for '{keywords}'")
        return results

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to search for videos on DuckDuckGo for '{keywords}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    videos = search_videos("Apple Vision Pro")
    with open('videos.json', 'w') as f:
        json.dump(videos, f, indent=4)
    subprocess.run(["code", "videos.json"])