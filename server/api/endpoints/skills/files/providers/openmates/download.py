################
# Default Imports
################
import sys
import os
import re
from cryptography.fernet import Fernet
from fastapi.responses import StreamingResponse
from server.cms.strapi_requests import get_strapi_upload, make_strapi_request
import io
from server.api.security.crypto import decrypt_file
import gc
from contextlib import contextmanager

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from fastapi import HTTPException
import requests


@contextmanager
def secure_decryption(encrypted_data, key):
    try:
        decrypted_file = decrypt_file(encrypted_data=encrypted_data, key=key)
        yield decrypted_file
    finally:
        # Explicitly overwrite the decrypted data
        if 'decrypted_file' in locals():
            decrypted_file = b'\x00' * len(decrypted_file)
        # Force garbage collection
        gc.collect()

async def download(
    api_token: str,
    file_path: str
) -> StreamingResponse:
    """
    Download and decrypt a file from the OpenMates server
    """
    add_to_log(module_name="OpenMates | API | Files | Providers | OpenMates | Download", state="start", color="yellow", hide_variables=True)
    add_to_log(f"Downloading and decrypting file from OpenMates server ...")

    # Extract file_id from file_path
    file_id = file_path.split("/")[-2]

    # Fetch the file information
    status_code, json_response = await make_strapi_request(
        method='get',
        endpoint='uploaded-files',
        filters=[{"field": "file_id", "operator": "$eq", "value": file_id}],
        populate=["file.url"]
    )

    if status_code == 200 and json_response.get("data") and len(json_response["data"]) == 1:
        file_url = json_response["data"][0]["attributes"]["file"]["data"]["attributes"]["url"]

        # Download the file using get_strapi_upload
        encrypted_file_response = await get_strapi_upload(file_url.split('/')[-1])

        # Read the content of the StreamingResponse
        encrypted_data = b''
        async for chunk in encrypted_file_response.body_iterator:
            encrypted_data += chunk
    else:
        add_to_log("No file found with the given file_id.", state="error")
        raise HTTPException(status_code=404, detail="The file doesn't exist. This can be for various reasons: the file might be expired and deleted, the URL might be incorrect, you might not have access to it, or the file might not exist in the first place.")

    with secure_decryption(encrypted_data, api_token+file_id) as decrypted_file:
        return StreamingResponse(io.BytesIO(decrypted_file), media_type="application/octet-stream")