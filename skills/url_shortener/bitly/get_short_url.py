import traceback
import sys
import os
import re
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error
from server.setup.load_secrets import load_secrets


def get_short_url(url: str) -> str:
    try:
        secrets = load_secrets()

        api_url = 'https://api-ssl.bitly.com/v4/shorten'
        headers = {
            'Authorization': 'Bearer ' + secrets["bitly_access_token"], 
            'Content-Type': 'application/json'
        }
        data = {'long_url': url}
        response = requests.post(api_url, headers=headers, json=data)
    
        if response.status_code != 200 and response.status_code != 201:
            process_error(
                file_name=os.path.basename(__file__),
                when_did_error_occure=f"While getting short URL via bitly. The status code was {response.status_code}:\n{response.text}",
                traceback=traceback.format_exc(),
                file_path=full_current_path,
                local_variables=locals(),
                global_variables=globals()
            )
            return url
        
        return response.json()["link"]
    
    except Exception:
        process_error(f"While getting short URL for {url}", traceback=traceback.format_exc())


if __name__ == '__main__':
    url = 'https://www.theverge.com/2023/11/13/23958823/nvidia-h200-ai-gpu-announced-specs-release-date'
    print(get_short_url(url))