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


def get_short_url(url: str) -> str:
    try:
        api_url = f'http://tinyurl.com/api-create.php?url={url}'
        response = requests.get(api_url)
        
        if response.status_code != 200:
            process_error(
                file_name=os.path.basename(__file__),
                when_did_error_occure=f"While getting short URL via tinyurl. The status code was {response.status_code}:\n{response.text}",
                traceback=traceback.format_exc(),
                file_path=full_current_path,
                local_variables=locals(),
                global_variables=globals()
            )
            return url
        
        return response.text
    
    except Exception:
        process_error(f"While getting short URL for {url}", traceback=traceback.format_exc())


if __name__ == '__main__':
    url = 'https://www.theverge.com/2023/11/13/23958823/nvidia-h200-ai-gpu-announced-specs-release-date'
    print(get_short_url(url))