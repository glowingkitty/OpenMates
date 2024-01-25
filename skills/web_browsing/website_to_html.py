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

from slugify import slugify
import wget

def website_to_offline(url: str) -> None:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Downloading website for offline use ...")

        filename = wget.download(url, out=f'{main_directory}temp_data/website_htmls/')
        add_to_log(f"Successfully downloaded the website for offline use: '{f'{main_directory}temp_data/website_htmls/{filename}.html'}'", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to download the website for offline use", traceback=traceback.format_exc())


if __name__ == "__main__":
    website_to_offline(url="https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request")