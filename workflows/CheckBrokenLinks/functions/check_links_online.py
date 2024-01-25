import requests
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from server.setup.load_config import load_config


def check_links_online(links,show_forwarding=False):
    try:
        config = load_config()
        headers = {'User-Agent': config["user_agent"]["official"]}

        # Ensure links is always a list
        if not isinstance(links, list):
            links = [links]

        online_count = 0
        offline_links = set()

        for link in links:
            response = requests.get(link,headers=headers, allow_redirects=True)
            
            # Check if the link is online or the url the link is forwarding to is online
            if response.status_code == 200:
                online_count += 1
                if (show_forwarding):
                    final_url = response.url
                    if final_url != link:
                        print(f"\033[93mForwarded: {link} -> {final_url}\033[0m")
            else:
                print(f"\033[91mOffline: {link}\033[0m")
                offline_links.update([link])

    except Exception:
        process_error("Failed checking if links are online", traceback=traceback.format_exc())


    print(f"\033[92mLinks online: {online_count}\033[0m")
    print(f"\033[91mLinks offline: {len(offline_links)}\033[0m")

    return {'online_count': online_count, 'offline_links': offline_links}





if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Check if link is online')
    parser.add_argument('url', type=str, help='What link?')
    args = parser.parse_args()

    
    is_online = check_links_online([args.url])
    print(is_online)