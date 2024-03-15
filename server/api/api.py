
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

import uvicorn
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI
from server.api.models import OutgoingMessage, IncomingMessage
from server.api.endpoints.process_message import process_message
from server.api.endpoints.get_mates import get_all_mates
from fastapi import Depends
from server.api.verify_token import verify_token

# Create a limiter instance
limiter = Limiter(key_func=get_remote_address)

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

# Add the limiter as middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)



# Adding all GET endpoints
@app.get("/mates", summary="Mates", description="This endpoint returns a list of all AI team mates on the server.")
def get_mates(token: str = Depends(verify_token)):
    return get_all_mates()




# Adding all POST endpoints
@app.post("/message",response_model=OutgoingMessage, summary="Message", description="This endpoint sends a message to an AI team mate and returns the response.")
def send_message(message: IncomingMessage, token: str = Depends(verify_token)):
    return process_message(message)



if __name__ == "__main__":
    uvicorn.run("server.api.api:app", host="0.0.0.0", port=8000, log_level="info")