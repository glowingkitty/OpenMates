
################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from fastapi import FastAPI
from server.api.models import OutgoingMessage
from server.api.endpoints.process_message import process_message
from server.api.endpoints.get_mates import get_mates

# execute with 'uvicorn server.api.api:app' from main directory

app = FastAPI(
    title="OpenMates API",
    description=(
        "Allows your code to interact with OpenMates server.\n"
        "# How to get started \n"
        "1. Login to your OpenMates account, go to the settings and find your API token there. \n"
        "2. Make a request to the endpoint you want to use. Make sure to include your 'token' in the header."
    ),
    version="1.0.0",
    redoc_url="/docs", 
    docs_url="/swagger_docs"
    )


def start_api():
    try:
        add_to_log(module_name="OpenMates | API", state="start", color="yellow")
        add_to_log("Starting the API ...")

        # Adding all GET endpoints
        app.get("/mates", summary="Mates", description="This endpoint returns a list of all AI team mates on the server.")(get_mates)

        # Adding all POST endpoints
        app.post("/message",response_model=OutgoingMessage, summary="Message", description="This endpoint sends a message to an AI team mate and returns the response.")(process_message)

        add_to_log("Successfully started the API", state="success")


    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to start the API", traceback=traceback.format_exc())
        return None
    

start_api()