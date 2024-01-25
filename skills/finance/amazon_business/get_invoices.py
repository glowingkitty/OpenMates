import sys
import os
import re
import time
import random
from playwright.sync_api import sync_playwright

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

def get_invoices():
    browser = None
    try:
        add_to_log(module_name="AmazonLogin", color="yellow", state="start")

        secrets = load_secrets()
        email_address = secrets['AMAZON_BUSINESS_EMAIL']
        password = secrets['AMAZON_BUSINESS_PASSWORD']
        
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)  # Set headless to False
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.amazon.de/b2b/aba/reports?reportType=items_report_1&dateSpanSelection=MONTH_TO_DATE&ref=hpr_redirect_report")
            
            # Fill the email and password fields
            for char in email_address:
                page.type('input[name="email"]', char)
                time.sleep(random.uniform(0.1, 0.4))  # Random delay between keystrokes
            for char in password:
                page.type('input[name="password"]', char)
                time.sleep(random.uniform(0.1, 0.4))  # Random delay between keystrokes
            
            # Random delay before clicking the submit button
            time.sleep(random.uniform(0.5, 2.0))
            
            # Click the submit button
            page.click('input[type="submit"]')
            
            # Add any additional actions here
            input("Press Enter to continue...")
            add_to_log("Amazon login script executed successfully", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to execute Amazon login script", traceback=traceback.format_exc())
    
    finally:
        if browser:
            try:
                browser.close()
            except Exception as e:
                print(f"Error while closing the browser: {e}")


if __name__ == "__main__":
    get_invoices()