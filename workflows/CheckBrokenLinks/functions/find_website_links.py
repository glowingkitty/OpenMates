import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import traceback
import sys
import os
import re
from urllib.parse import urljoin


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from server.setup.load_config import load_config

def find_links(url: str) -> list:
    try:
        config = load_config()
        headers = {'User-Agent': config["user_agent"]["official"]}
        
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Fetch all 'a' tags
        a_tags = [urljoin(url, a['href']) for a in soup.find_all('a', href=True)]
        
        # Fetch all 'iframe' tags
        iframe_tags = [urljoin(url, iframe['src']) for iframe in soup.find_all('iframe', src=True) if 'src' in iframe.attrs]
        
        # Fetch all 'embed' tags
        embed_tags = [urljoin(url, embed['src']) for embed in soup.find_all('embed', src=True) if 'src' in embed.attrs]
        
        # Fetch all 'img' tags
        img_tags = [urljoin(url, img['src']) for img in soup.find_all('img', src=True) if 'src' in img.attrs]
        
        # Combine all the links
        all_links = a_tags + iframe_tags + embed_tags + img_tags

        # Filter all_links to only include URLs that start with 'http'
        all_links = [link for link in all_links if link.startswith('http')]
        
        return all_links
        
    except Exception:
        process_error("Failed finding links", traceback=traceback.format_exc())
        return []



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Find all links')
    parser.add_argument('start_url', type=str, help='Where to start?')
    args = parser.parse_args()

    
    links = find_links(args.start_url)
    print(links)