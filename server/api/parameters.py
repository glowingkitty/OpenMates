
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

from server.api.models.mates import (
    MatesAskOutput, 
    MatesGetAllOutput, 
    Mate, 
    MateUpdateOutput,
    MatesCreateOutput,
    mates_get_all_output_example
    )


def generate_responses(status_codes):
    descriptions = {
        "200": "Successful Response",
        "201": "Successful Creation",
        "400": "Bad Request",
        "401": "Unauthorized",
        "403": "Forbidden",
        "404": "Not Found",
        "409": "Conflict",
        "422": "Validation Error",
        "500": "Internal Server Error"
    }
    
    responses = {}
    for code in status_codes:
        responses[str(code)] = {"description": descriptions.get(str(code), "Unknown Status Code"), "model": None}
    
    return responses


def set_example(openapi_schema, path, method, request_or_response, example, response_code=None):
    # Ensure the path exists
    if path not in openapi_schema["paths"]:
        openapi_schema["paths"][path] = {}

    # Ensure the method exists
    if method not in openapi_schema["paths"][path]:
        openapi_schema["paths"][path][method] = {}

    # Ensure the request_or_response exists
    if request_or_response not in openapi_schema["paths"][path][method]:
        openapi_schema["paths"][path][method][request_or_response] = {}

    if request_or_response == "responses":
        # Ensure the response_code exists
        if response_code not in openapi_schema["paths"][path][method][request_or_response]:
            openapi_schema["paths"][path][method][request_or_response][response_code] = {}

        # Ensure the 'content' exists
        if "content" not in openapi_schema["paths"][path][method][request_or_response][response_code]:
            openapi_schema["paths"][path][method][request_or_response][response_code]["content"] = {}

        # Ensure the 'application/json' exists
        if "application/json" not in openapi_schema["paths"][path][method][request_or_response][response_code]["content"]:
            openapi_schema["paths"][path][method][request_or_response][response_code]["content"]["application/json"] = {}

        # Set the example
        openapi_schema["paths"][path][method][request_or_response][response_code]["content"]["application/json"]["example"] = example
    else:
        # Ensure the 'content' exists
        if "content" not in openapi_schema["paths"][path][method][request_or_response]:
            openapi_schema["paths"][path][method][request_or_response]["content"] = {}

        # Ensure the 'application/json' exists
        if "application/json" not in openapi_schema["paths"][path][method][request_or_response]["content"]:
            openapi_schema["paths"][path][method][request_or_response]["content"]["application/json"] = {}

        # Set the example
        openapi_schema["paths"][path][method][request_or_response]["content"]["application/json"]["example"] = example


endpoint_metadata = {
    "ask_mate":{
        "response_model":MatesAskOutput,
        "summary": "Ask",
        "description": "<img src='images/mates/ask.png' alt='Send a ask to one of your AI team mates. It will then automatically decide what skills to use to answer your question or fulfill the task.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "get_all_mates":{
        "response_model":MatesGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/mates/get_all.png' alt='Get an overview list of all AI team mates currently active on the OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500]),
    },
    "get_mate":{
        "response_model":Mate,
        "summary": "Get mate",
        "description": "<img src='images/mates/get_mate.png' alt='Get all details about a specific mate. Including system prompt, available skills and more.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "create_mate":{
        "response_model":MatesCreateOutput,
        "summary": "Create",
        "description": "<img src='images/mates/create.png' alt='Create a new mate on the OpenMates server, with a custom system prompt, accessible skills and other settings.'>",
        "responses": generate_responses([201, 400, 401, 403, 409, 422, 500]),
        "status_code": 201
    },
    "update_mate":{
        "response_model":MateUpdateOutput,
        "summary": "Update",
        "description": "<img src='images/mates/update.png' alt='Update an existing mate on the server. For example change the system prompt, the available skills and more.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    },
}


tags_metadata = [
    {
        "name": "Mates",
        "description": "<img src='images/mates.png' alt='Mates are your AI team members. They can help you with various tasks. Each mate is specialized in a different area.'>"
    },
    {
        "name": "Software",
        "description": "<img src='images/software.png' alt='Your team mates can interact with a wide range of software, on your behalf. For example: ChatGPT, Notion, RSS, SevDesk, YouTube, Claude, StableDiffusion, Firefox, Dropbox.'>"
    },
    {
        "name": "Skills",
        "description": "<img src='images/skills.png' alt='Your team mate can use a wide range of software skills. Or, you can call them directly via the API.'>"
    },
    {
        "name": "Workflows",
        "description": "<img src='images/workflows.png' alt='A skill is powerful. Combining multiple skills in a workflow is magical.'>"
    },
    {
        "name": "Tasks",
        "description": "<img src='images/tasks.png' alt='A task is a scheduled run of a single skill or a whole workflow. It can happen once, or repeated.'>"
    },
    {
        "name": "Billing",
        "description": "<img src='images/billing.png' alt='Manage your billing settings, download invoices and more.'>"
    },
    {
        "name": "Server",
        "description": "<img src='images/server.png' alt='Manage your OpenMates server. Change settings, see how the server is doing and more.'>"
    },
    {
        "name": "Teams",
        "description": "<img src='images/teams.png' alt='Manage the teams on your OpenMates server.'>"
    },
    {
        "name": "Users",
        "description": "<img src='images/users.png' alt='Manage user accounts of a team. A user can get personalized responses from mates and access to the OpenMates API.'>"
    }
]


input_parameter_descriptions = {
    "team_url": {
        "description": "The URL of the team",
        "example": "openmates_enthusiasts"
    },
    "token": {
        "description": "The authentication token",
        "example": "123456789"
    },
    "mate_username":{
        "description": "The username of the AI team mate",
        "example": "sophia"
    }
}

