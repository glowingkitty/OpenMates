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

from server import *
################

import httpx
from dotenv import load_dotenv
from typing import Optional, Dict, List
from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse

# Load the .env file
load_dotenv()

STRAPI_URL = os.getenv('STRAPI_URL')
STRAPI_API_TOKEN = os.getenv('STRAPI_API_TOKEN')

async def make_strapi_request(method: str, endpoint: str, data: Optional[Dict] = None, fields: Optional[List[str]] = None, populate: Optional[List[str]] = None) -> JSONResponse:
    async with httpx.AsyncClient() as client:
        try:
            params = "?"
            if fields:
                # for every field in fields, add it to the params with the index as key
                for i, field in enumerate(fields):
                    params += f"fields[{i}]={field}&"
            if populate:
                # add the populate fields to the params
                populate_dict = {}
                for item in populate:
                    entity, field = item.split('.')
                    if entity not in populate_dict:
                        populate_dict[entity] = []
                    populate_dict[entity].append(field)

                for entity, fields in populate_dict.items():
                    for i, field in enumerate(fields):
                        params += f"populate[{entity}][fields][{i}]={field}&"
                

            # remove the last '&' from the params, if it exists
            if params[-1] == '&':
                params = params[:-1]
                
            strapi_url = f"{STRAPI_URL}/api/{endpoint}{params}"

            strapi_headers = {"Authorization": f"Bearer {STRAPI_API_TOKEN}"}
            if method.lower() == 'get':
                strapi_response = await client.get(strapi_url, headers=strapi_headers)
            elif method.lower() == 'post':
                strapi_response = await client.post(strapi_url, headers=strapi_headers, json=data)
            elif method.lower() == 'patch':
                strapi_response = await client.patch(strapi_url, headers=strapi_headers, json=data)
            elif method.lower() == 'delete':
                strapi_response = await client.delete(strapi_url, headers=strapi_headers)
            else:
                raise ValueError(f"Invalid method: {method}")
            strapi_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HTTPException(status_code=401, detail="401 Error: Invalid token or insufficient permissions")
            else:
                raise HTTPException(status_code=exc.response.status_code, detail=f"A {exc.response.status_code} error occured.")
        return JSONResponse(status_code=strapi_response.status_code, content=strapi_response.json())
    

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