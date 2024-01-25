import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from functions.find_website_links import find_links
from functions.check_links_online import check_links_online
from functions.filter_for_domain_links import filter_for_domain_links
from server.setup.load_config import load_config


class BrokenLinkObserver:
    def __init__(self):
        config = load_config()
        
        self.domain = "glowingkitty.com"
        self.start_url = "https://"+self.domain
        self.sub_domains = ["shop","install"]
        self.exclude_paths_from_scraping = ["cdn/shop/"]
        self.checked_urls = set()
        self.origin_urls = {}
        self.headers = {'User-Agent': config["user_agent"]["official"]}
        self.online_links_counter = 0
        self.offline_links = set()

    def process(self):
        try:
            ## TODO:

            # scrape for all domain related sub pages (and notify if any of them are offline)

            # scrape all those pages for links that lead to images, files, external pages

            # add links to 3d models, documents and more from github json

            # check all links if they are online






            # start by finding all links on main page
            print('Checking url: '+self.start_url)
            main_page_links = find_links(
                url=self.start_url,
                headers=self.headers
                )
            self.online_links_counter+=1
            self.checked_urls.update([self.start_url])

            # check if all the links are online
            output = check_links_online(
                links=main_page_links,
                headers=self.headers
                )
            self.online_links_counter += output["online_count"]
            self.offline_links.update(output["offline_links"])
            self.checked_urls.update(main_page_links)

            next_pages = filter_for_domain_links(
                links=self.checked_urls,
                start_url=self.start_url,
                domain=self.domain,
                sub_domains=self.sub_domains,
                exclude_paths=self.exclude_paths_from_scraping
            )

            # for each remaining unique url, repeat the process
            for url in next_pages:
                print('\nChecking url: '+url)
                page_links = find_links(
                    url=url,
                    headers=self.headers
                )

                new_links = [link for link in page_links if link not in self.checked_urls]

                output = check_links_online(
                    links=new_links,
                    headers=self.headers
                )

                self.online_links_counter += output["online_count"]
                self.offline_links.update(output["offline_links"])
                self.checked_urls.update(new_links)

                
            print("Completed.")
            print(f"\033[92mLinks online: {self.online_links_counter}\033[0m")
            print(f"\033[91mLinks offline: {len(self.offline_links)}\033[0m")
        
        except Exception:
            process_error(
                file_name=os.path.basename(__file__),
                when_did_error_occure="While processing the function",
                traceback=traceback.format_exc(),
                file_path=full_current_path,
                local_variables=locals(),
                global_variables=globals()
            )



# first scrape start_url

# then search for all files generated based on  ... 3dfiles.json on github, and documents.json and so on
# make sure all those links also work

# then also check all urls on documents in figma (DIY guide, schematic and so on, bit.ly links)


if __name__ == "__main__":
    observer = BrokenLinkObserver()
    observer.process()
    