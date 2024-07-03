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
import random
from fake_useragent import UserAgent


def scrape_meetup_events() -> None:
    try:
        add_to_log(module_name="MeetupScrape", color="yellow", state="start")
        add_to_log("Scraping Meetup events ...")

        # Create a UserAgent object
        ua = UserAgent()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)  # Set headless=False if you want to see the browser
            page = browser.new_page()
            user_agent = ua.random
            page.set_extra_http_headers({'User-Agent': user_agent})

            page.goto('https://www.meetup.com/find/?location=de--Berlin&source=EVENTS&keywords=startup&customStartDate=2024-02-01T18%3A00%3A00-05%3A00&customEndDate=2024-02-29T17%3A59%3A00-05%3A00&eventType=inPerson')

            # Scroll down a few times
            for _ in range(3):  # Adjust the range as needed
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(random.randint(2000, 4000))  # Wait for a random time between 2 and 4 seconds for the page to load
            
            # Adjust the selectors based on the actual page structure
            event_elements = page.query_selector_all('div[data-eventref]')
            add_to_log(f"Found {len(event_elements)} event elements", state="success")
            events = []
            for event_element in event_elements:
                event_name = event_element.query_selector('h2').inner_text()
                event_date = event_element.query_selector('h3').inner_text()
                event_link = event_element.query_selector('a').get_attribute('href')
                events.append({'name': event_name, 'date':event_date, 'link': event_link})
            
            add_to_log(f"Found {len(events)} events", state="success")
            for event in events:
                print(event)
            
            browser.close()
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to scrape Meetup events. Error: {str(e)}", traceback=traceback.format_exc())

if __name__ == "__main__":
    scrape_meetup_events()