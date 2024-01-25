from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException, NoSuchFrameException
from selenium.webdriver.common.by import By


def accept_cookies(driver):
    try:
        driver.execute_script("""
            var iframes = document.getElementsByTagName('iframe');
            for(var i = 0; i < iframes.length; i++) {
                iframes[i].parentNode.removeChild(iframes[i]);
            }
        """)
        
        cookie_buttons = [
            {"type": "id", "value": "accept-cookies"},
            {"type": "class", "value": "cookie-accept"},
            {"type": "xpath", "value": "//button[contains(.,'Accept') or contains(.,'Agree') or contains(.,'OK')]"},
            {"type": "xpath", "value": "//button[contains(.,'accept') or contains(.,'agree') or contains(.,'OK')]"},
            {"type": "xpath", "value": "//button[contains(.,'Akzeptieren')]"},
            {"type": "xpath", "value": "//button[contains(.,'akzeptieren')]"},
            # Add more patterns as necessary
        ]
        
        # Function to search and click cookie buttons
        for button in cookie_buttons:
            try:
                if button["type"] == "id":
                    driver.find_element(By.ID, button["value"]).click()
                elif button["type"] == "class":
                    driver.find_element(By.CLASS_NAME, button["value"]).click()
                elif button["type"] == "xpath":
                    driver.find_element(By.XPATH, button["value"]).click()
            except (NoSuchElementException, ElementNotInteractableException):
                pass  # If the element is not found or not interactable, try the next selector

        return driver
    except Exception:
        print("Could not accept cookies.")