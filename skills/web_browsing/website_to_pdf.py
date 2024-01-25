################

# Default Imports

################
import sys
import os
import re
import inspect
from playwright.sync_api import sync_playwright

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from slugify import slugify


def website_to_pdf(url: str) -> None:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Converting website to PDF ...")

        config = load_config()

        url = url.rstrip('/')
        # if no filename is set, use slugified url as filename
        # get website name (between first and second dot)
        website_name = url.split('.')[1]
        # get website title (the last part of the list, separated by slashes)
        website_title = url.split('/')[-1]
        # slugify the full url
        filename = slugify(f'{website_name}-{website_title}')

        # create the directory if it doesn't exist
        os.makedirs(f"{main_directory}temp_data/website_pdfs/", exist_ok=True)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=config["user_agent"]["official"])
            page = context.new_page()
            page.set_viewport_size({"width": 600, "height": 1024})
            page.goto(url)
            page.pdf(path=f"{main_directory}temp_data/website_pdfs/{filename}.pdf")
            browser.close()
        
        add_to_log(f"Successfully saved the website as PDF: '{f'{main_directory}temp_data/website_pdfs/{filename}.pdf'}'", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to save the website as PDF", traceback=traceback.format_exc())

if __name__ == "__main__":
    website_to_pdf(url="https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request")