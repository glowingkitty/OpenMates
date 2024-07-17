# How to add a new API endpoint

**1. Update api.py - [`server/api/api.py`](../api.py):**
   - Add `async def` function for new endpoint, including router and limiter
     - Example:
       - **POST** `/skills/chatgpt/ask` *(ask a question to ChatGPT from OpenAI)*: [`server/api/api.py`](../api.py)
   - Add missing imports to `api.py`:
     - Example for **POST** `/skills/chatgpt/ask`:
       - `from server.api.models.skills.chatgpt.skills_chatgpt_ask import (
    ChatGPTAskInput,
    chatgpt_ask_input_example,
    chatgpt_ask_output_example
)`
       - `from server.api.endpoints.skills.chatgpt.ask import ask as ask_chatgpt_processing`
       - `from server.api.parameters import (
    ...
    skills_chatgpt_endpoints,
    ...
)`
   - Add missing set_example() calls to `api.py`:
     - Example for **POST** `/skills/chatgpt/ask`:
       - `set_example(openapi_schema, "/v1/{team_slug}/skills/chatgpt/ask", "post", "requestBody", chatgpt_ask_input_example)`
       - `set_example(openapi_schema, "/v1/{team_slug}/skills/chatgpt/ask", "post", "responses", chatgpt_ask_output_example, "200")`

**2. Create models python file - [`server/api/models/{router}/`](../models/):**
   - Add `.py` file for new endpoint. This `.py` file is named similar to the endpoint function and contains the FastAPI models for this endpoint and doc examples:
     - Input
     - Output
     - examples for FastAPI docs
   - Example:
     - [`server/api/models/skills/chatgpt/skills_chatgpt_ask.py`](../models/skills/chatgpt/skills_chatgpt_ask.py)

**3. Update parameters.py - [`server/api/parameters.py`](../parameters.py):**
   - Add in `endpoint_metadata` the new endpoint
   - Add missing imports

**4. Create endpoint python file - [`server/api/endpoints/{router}/`](../endpoints/):**
   - Add `.py` file for new endpoint, which does the actual processing of the request and which returns the response.
   - Example:
     - [`server/api/endpoints/skills/chatgpt/ask.py`](../endpoints/skills/chatgpt/ask.py)