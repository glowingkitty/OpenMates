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
################

import httpx
from dotenv import load_dotenv
from typing import Optional, Dict, List, Tuple
from fastapi import HTTPException, Response
from fastapi.responses import StreamingResponse
import base64
from io import BytesIO

# Load the .env file
load_dotenv()

STRAPI_URL = os.getenv('STRAPI_URL')
STRAPI_API_TOKEN = os.getenv('STRAPI_API_TOKEN')

def add_params(params, populate) -> str:
    for field in populate:
        parts = field.split('.')
        params = build_params(params, parts, "populate", "")
    return params


def build_params(params, parts, prefix, postfix) -> str:
    if len(parts) == 1:
        params += f"{prefix}[fields][0]={parts[0]}{postfix}&"
    else:
        params = build_params(params, parts[1:], f"{prefix}[{parts[0]}][populate]", postfix)
    return params


def get_nested(dictionary, key_path, stop_at_last_key=False):
    if dictionary is None:
        return None

    if not isinstance(dictionary, dict):
        raise ValueError(f"dictionary must be a dictionary, but got: {type(dictionary)}")

    if not key_path:
        return dictionary

    keys = key_path.split('.')
    for i, key in enumerate(keys):
        while isinstance(dictionary, dict) and key not in dictionary:
            if "attributes" in dictionary:
                dictionary = dictionary["attributes"]
            elif "data" in dictionary:
                if isinstance(dictionary["data"], list) and dictionary["data"]:
                    dictionary = dictionary["data"][0]
                elif isinstance(dictionary["data"], dict) and dictionary["data"]:
                    dictionary = dictionary["data"]
                else:
                    return None
            else:
                return None

        if isinstance(dictionary, dict):
            if stop_at_last_key and i == len(keys) - 1:
                return dictionary.get(key)
            dictionary = dictionary.get(key)
        elif isinstance(dictionary, list):
            try:
                index = int(key)
                if 0 <= index < len(dictionary):
                    dictionary = dictionary[index]
                else:
                    return None
            except ValueError:
                return None
        else:
            return None

    # Automatically return the "data" if it's present in the final result
    if isinstance(dictionary, dict) and "data" in dictionary and isinstance(dictionary["data"], list):
        return dictionary["data"]

    return dictionary



async def make_strapi_request(
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        fields: Optional[List[str]] = None,
        populate: Optional[List[str]] = None,
        filters: Optional[List[Dict]] = None,
        page: int = 1,
        pageSize: int = 25,
        ) -> Tuple[int, Dict]:
    async with httpx.AsyncClient() as client:
        try:
            if method == "get":
                params = "?"
                # define which fields to return
                if fields:
                    for i, field in enumerate(fields):
                        params += f"fields[{i}]={field}&"
                # define which relationships to add
                if populate:
                    params = add_params(params, populate)

                # define filters
                if filters:
                    for filter in filters:
                        field_path = filter['field'].split('.')
                        # turn a teams.slug into [teams][slug]
                        field_path_str = "[" + "][".join(field_path) + "]"

                        # add the filter to the params
                        params += f"filters{field_path_str}[{filter['operator']}]={filter['value']}&"

                # add num_results and page to params
                params += f"pagination[page]={page}&pagination[pageSize]={pageSize}"

                # remove the last '&' from the params, if it exists
                if params[-1] == '&':
                    params = params[:-1]
            else:
                params = ""

            strapi_url = f"{STRAPI_URL}/api/{endpoint}{params}"

            strapi_headers = {"Authorization": f"Bearer {STRAPI_API_TOKEN}"}
            if method.lower() == 'get':
                strapi_response = await client.get(strapi_url, headers=strapi_headers)
            elif method.lower() == 'post':
                strapi_response = await client.post(strapi_url, headers=strapi_headers, json=data)
            elif method.lower() == 'put':
                strapi_response = await client.put(strapi_url, headers=strapi_headers, json=data)
            elif method.lower() == 'delete':
                strapi_response = await client.delete(strapi_url, headers=strapi_headers)
            else:
                raise ValueError(f"Invalid method: {method}")
            strapi_response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HTTPException(status_code=401, detail="401 Error: Invalid token or insufficient permissions")
            else:
                add_to_log(f"A {exc.response.status_code} error occured.", module_name="OpenMates | API | Strapi Requests", state="error")
                add_to_log(exc.response.json(), module_name="OpenMates | API | Strapi Requests", state="error")
                raise HTTPException(status_code=exc.response.status_code, detail=f"A {exc.response.status_code} error occured.")

        return strapi_response.status_code, strapi_response.json()


async def get_strapi_upload(url: str) -> Response:
    async with httpx.AsyncClient() as client:
        try:
            strapi_response = await client.get(f"{STRAPI_URL}/uploads/{url}")
            strapi_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HTTPException(status_code=401, detail="401 Error: Invalid token or insufficient permissions")
            else:
                raise HTTPException(status_code=exc.response.status_code, detail=f"A {exc.response.status_code} error occured.")

        return StreamingResponse(strapi_response.iter_bytes(), media_type=strapi_response.headers['Content-Type'])




async def upload_file_to_strapi(file_data: bytes, file_name: str) -> Dict:
    async with httpx.AsyncClient() as client:
        try:
            file = BytesIO(file_data)
            files = {'files': (file_name, file, 'application/octet-stream')}

            headers = {
                "Authorization": f"Bearer {STRAPI_API_TOKEN}"
            }

            strapi_response = await client.post(
                f"{STRAPI_URL}/api/upload",
                headers=headers,
                files=files
            )
            strapi_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"Upload failed: {exc.response.text}")

        return strapi_response.json()


async def delete_file_from_strapi(strapi_file_id: int) -> Dict:
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "Authorization": f"Bearer {STRAPI_API_TOKEN}"
            }

            strapi_response = await client.delete(
                f"{STRAPI_URL}/api/upload/files/{strapi_file_id}",
                headers=headers
            )
            strapi_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"File deletion failed: {exc.response.text}")

        return strapi_response.json()


async def create_uploaded_file_entry(file_id: str, filename: str, additional_data: Optional[Dict] = None) -> Dict:
    async with httpx.AsyncClient() as client:
        try:
            data = {
                "data": {
                    "file": file_id,
                    "filename": filename,
                    **(additional_data or {})
                }
            }
            strapi_response = await client.post(
                f"{STRAPI_URL}/uploaded-files",
                headers={"Authorization": f"Bearer {STRAPI_API_TOKEN}"},
                json=data
            )
            strapi_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"Entry creation failed: {exc.response.text}")

        return strapi_response.json()