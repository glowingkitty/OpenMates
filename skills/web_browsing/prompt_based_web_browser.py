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

from skills.intelligence.load_systemprompt import load_systemprompt

def prompt_based_web_browser(start_page: str, headless: bool = True) -> dict:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Starting a prompt based web browsing session ...")

        config = load_config()

        # load the systemprompt
        interact_systemprompt = load_systemprompt(special_usecase="web_browsing/prompt_based_web_browser/interact")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=config["user_agent"]["official"])
            page = context.new_page()
            page.goto(start_page)

            # keep the browser open
            input("Press Enter to close the browser ...")
        

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("An error occured while browsing the web", traceback=traceback.format_exc())

if __name__ == "__main__":
    prompt_based_web_browser(headless = False, start_page="https://theverge.com")