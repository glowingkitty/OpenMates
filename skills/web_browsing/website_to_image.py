################

# Default Imports

################
import sys
import os
import re
from playwright.sync_api import sync_playwright

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from slugify import slugify
import time


def close_cookie_banner(page):
    time.sleep(2)  # Wait for the cookie banner to appear
    # Common words for cookie accept buttons
    cookie_words = ["accept", "agree", "akzeptieren", "ok"]

    # Create case-insensitive selectors for each word
    cookie_selectors = [f'button[name*="{word}" i]' for word in cookie_words]

    # Add more specific selectors as needed
    cookie_selectors.extend([
        'button[aria-label="Accept cookies"]',  # Example selector
        'button[aria-label="Agree"]',           # Example selector
        # Add more selectors as needed
    ])
    
    for selector in cookie_selectors:
        if page.is_visible(selector):
            page.click(selector)
            add_to_log(f"Clicked cookie banner button with selector: {selector}", state="info")
            break  # Stop after the first match to avoid clicking multiple buttons



def website_to_image(url: str, headless: bool = True) -> None:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Taking a full page screenshot ...")

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
        os.makedirs(f"{main_directory}temp_data/website_screenshots/", exist_ok=True)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=config["user_agent"]["official"])
            page = context.new_page()
            # page.set_viewport_size({"width": 375, "height": 812})
            page.goto(url)
            close_cookie_banner(page)
            page.screenshot(path=f"{main_directory}temp_data/website_screenshots/{filename}.png", full_page=True)
            browser.close()
        
        add_to_log(f"Successfully took a screenshot of {url}. You can find it here: {main_directory}temp_data/website_screenshots/{filename}.png", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to take a full page screenshot", traceback=traceback.format_exc())

if __name__ == "__main__":
    # url = "https://www.theverge.com/2023/11/29/23979850/tesla-cybertruck-delivery-design-production-problems-delay"  # Replace with the desired URL
    url = "https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request"  # Replace with the desired URL
    website_to_image(url, headless=False)