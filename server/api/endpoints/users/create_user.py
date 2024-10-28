from typing import List, Optional, Union, Dict, Literal
from server.cms.cms import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.models.users.users_create import UsersCreateOutput, UsersCreateInput
from server.api.endpoints.users.create_new_api_token import create_new_api_token
from server.api.security.crypto import encrypt, hashing


async def create_user(
        input: UsersCreateInput
    ) -> UsersCreateOutput:
    """
    Create a new user on the team
    """

    # generate new API token
    create_new_token_output = await create_new_api_token()
    full_token = create_new_token_output["api_token"]
    uid = create_new_token_output["api_token"][:32]
    api_token = create_new_token_output["api_token"][32:]

    # TODO encrypt data before sending to strapi
    name_encrypted = encrypt(input.name)
    email_encrypted = encrypt(input.email)
    password_hash = hashing(input.password)
    api_token_hash = hashing(api_token)

    # TODO send data to strapi to create the user

    # TODO return the user data

    return {
        "id": 2,
        "name": name,
        "username": username,
        "email": email,
        "api_token": full_token,
        "teams": [
            {
                "id": 1,
                "name": "AI Sales Team",
                "slug": "ai-sales-team"
            }
        ],
        "balance_in_EUR": 0.0,
        "app_settings": {},
        "other_settings": {},
        "projects": [],
        "goals": [],
        "todos": [],
        "recent_topics": []
    }