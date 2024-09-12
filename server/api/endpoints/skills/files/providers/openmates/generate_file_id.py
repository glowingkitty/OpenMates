################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
from server.cms.cms import make_strapi_request

################

import uuid


async def generate_file_id() -> str:
    """
    Generate a unique file ID
    """
    while True:
        file_id = uuid.uuid4().hex[:10]
        status_code, response = await make_strapi_request(
            method='get',
            endpoint='uploaded-files',
            filters=[{
                'field': 'file_id',
                'operator': '$eq',
                'value': file_id
            }]
        )
        if status_code == 200 and not response['data']:
            add_to_log(f'Generated file ID: {file_id}')
            # If no files are found with this ID, return it
            return file_id
        else:
            add_to_log(f'File ID {file_id} already exists')