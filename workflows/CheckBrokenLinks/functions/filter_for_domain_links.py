################
# Default Imports
################
import sys
import os
import re
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)
from server import *


################

def filter_domain_specific_links(
        links: list,
        domain: str,
        protocol: str = "https",
        sub_domains: list = [],
        exclude_paths: list = []) -> set:
    try:
        add_to_log(module_name="domain_link_filter", color="yellow", state="start")
        
        add_to_log("Filtering for domain-specific links.")

        start_urls = [{protocol + "://" + sub + "." + domain for sub in sub_domains}, {protocol + "://" + domain}]
        start_urls = tuple(url for sublist in start_urls for url in sublist)  # Flatten the list of sets and convert to tuple
        image_extensions = [".jpg", ".jpeg", ".png", ".svg"]

        filtered_links = {url for url in links
                          if url.startswith(start_urls) and
                          not url.endswith(tuple(image_extensions)) and
                          all(exclude_path not in url for exclude_path in exclude_paths)}

        add_to_log(f"Filtered {len(filtered_links)} links for domain {domain}.", state="success")

        return filtered_links
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to filter domain-specific links", traceback=traceback.format_exc())
        return None
    

# Test the function
if __name__ == "__main__":
    test_links = [
        "https://test.com",
        "https://glowingkitty.com/products",
        "https://glowingkitty.com/image.svg"
    ]
    test_domain = "glowingkitty.com"
    test_sub_domains = ["shop", "install"]

    filtered_test_links = filter_domain_specific_links(
        links=test_links,
        domain=test_domain,
        sub_domains=test_sub_domains
    )
    add_to_log(filtered_test_links)