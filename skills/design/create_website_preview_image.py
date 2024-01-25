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

from skills.tinyurl.get_short_url import get_short_url

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
from selenium import webdriver
from slugify import slugify


def create_website_preview_image(
        url: str,
        use_existing_file_if_exists: bool = False) -> str:
    try:
        add_to_log(state="start", module_name="Design", color="yellow")
        add_to_log(f"Start creating a preview image for the URL {url} ...")

        filename = slugify(url)
        folderpath = f'{main_directory}temp_data/rss/article_images'
        filepath = f'{main_directory}temp_data/rss/article_images/{filename}.png'

        # check if file already exists, if so, return it
        if use_existing_file_if_exists and os.path.exists(filepath):
            add_to_log(f"\U00002714 Using existing file: {filename}.png")
            return filepath

        # get the website logo from the url (favicon), via bs4
        response = requests.get(url)
        if response.status_code != 200:
            add_to_log(    state="error",
                message=f"create_website_preview_image error: {response.status_code} for url {url}"
                )
            return None
        
        article_soup = BeautifulSoup(response.content, 'html.parser')

        # get the titel of the website via meta tag
        title = article_soup.find("meta", property="og:title")
        
        # get the source name of the website via meta tag
        source_name = article_soup.find("meta", property="og:site_name")

        # create the short url
        short_url = get_short_url(url=url)


        # load the index.html file and replace the text of the item with the class name "title" and "source-name"
        with open(f'{main_directory}apps/design/article_image/index.html', 'r') as f:
            html = f.read()
            soup = BeautifulSoup(html, 'html.parser')
            soup.find("b", {"class": "title"}).string = title['content']
            soup.find("b", {"class": "source-name"}).string = source_name['content']
            soup.find("b", {"class": "shorturl"}).string = short_url.replace("https://", "").replace("http://", "").upper()
            with open(f'{main_directory}apps/design/article_image/index.html', 'w') as f:
                f.write(str(soup))

        # get the favicon from the url, via bs4
        favicon_link = article_soup.find("link", rel="icon")
        if favicon_link is None:
            favicon_link = article_soup.find("link", rel="shortcut icon")
        if favicon_link is None:
            favicon = urljoin(url, '/favicon.ico')
        else:
            favicon = urljoin(url, favicon_link["href"])

        # get the website image from the url via meta tag
        website_image_meta = article_soup.find("meta", property="og:image")
        if website_image_meta is None:
            add_to_log(f"No website image found for url {url}")
            website_image_url = None
        else:
            website_image_url = website_image_meta['content']
        

        # download the favicon and website image
        favicon_response = requests.get(favicon)
        with open(f'{main_directory}apps/design/article_image/public/logo@2x.png', 'wb') as f:
            f.write(favicon_response.content)

        website_image_response = requests.get(website_image_url)
        with open(f'{main_directory}apps/design/article_image/public/preview-image@2x.png', 'wb') as f:
            f.write(website_image_response.content)


        # Set up Chrome options
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument("--headless")
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument("--hide-scrollbars")

        # Set window size and pixel density
        window_width = 480
        window_height = 270
        pixel_density = 4

        chrome_options.add_argument(f"--window-size={window_width},{window_height}")
        chrome_options.add_experimental_option("mobileEmulation", {"deviceMetrics": {"width": window_width, "height": window_height, "pixelRatio": pixel_density}})

        # Set up Chrome driver
        driver = webdriver.Chrome(options=chrome_options)

        # Load the page
        article_preview_html = f"file:///{main_directory}apps/design/article_image/index.html"
        driver.get(article_preview_html)

        # Save as image
        # make sure directory exists
        os.makedirs(folderpath, exist_ok=True)
        time.sleep(0.5)
        driver.save_screenshot(filepath)

        driver.quit()

        # delete the created image files
        os.remove(f'{main_directory}apps/design/article_image/public/logo@2x.png')
        os.remove(f'{main_directory}apps/design/article_image/public/preview-image@2x.png')

        # reset the index.html file
        with open(f'{main_directory}apps/design/article_image/index.html', 'r') as f:
            html = f.read()
            soup = BeautifulSoup(html, 'html.parser')
            soup.find("b", {"class": "title"}).string = ""
            soup.find("b", {"class": "source-name"}).string = ""
            soup.find("b", {"class": "shorturl"}).string = ""
            with open(f'{main_directory}apps/design/article_image/index.html', 'w') as f:
                f.write(str(soup))

        add_to_log(state="success", message=f"Successfully created a preview image for the URL {url}.")
        add_to_log(state="success", message=filepath)

        return filepath
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed creating preview image for a URL", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    url = "https://www.theverge.com/23951210/energy-secretary-jennifer-granholm-interview-sustainability"
    create_website_preview_image(url)