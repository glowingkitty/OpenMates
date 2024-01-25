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

def search_images(keywords: str, max_results: int = 10) -> list:
    try:
        add_to_log(module_name="Images | Search", color="yellow", state="start")
        add_to_log(f"Searching for images on DuckDuckGo with the keywords: {keywords}")

        images = []
        
        with DDGS() as ddgs:
            keywords = keywords
            ddgs_images_gen = ddgs.images(
            keywords,
            region="wt-wt",
            safesearch="off",
            size=None,
            # color="Monochrome",
            type_image=None,
            layout=None,
            license_image=None,
            max_results=max_results,
            )
            for image in ddgs_images_gen:
                images.append(image)

        add_to_log(f"Found {len(images)} images on DuckDuckGo for '{keywords}'")
        return images

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to search for images on DuckDuckGo for '{keywords}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    import json
    import subprocess

    images = search_images("glowingkitty")
    with open('images.json', 'w') as f:
        json.dump(images, f, indent=4)
    subprocess.run(["code", "images.json"])