from server.api.docs import *


bearer_scheme = HTTPBearer(
    scheme_name="Bearer Token",
    description="""Enter your bearer token. Here's an example of how to use it in a request:

    ```python
    import requests

    url = "https://{server_url}/{endpoint}"
    headers = {"Authorization": "Bearer {your_token}"}

    # Make a get request (replace with post, patch, etc. as needed)
    response = requests.get(url, headers=headers)
    print(response.json())
    ```
    """
)

def generate_python_example(method, path, params=None, body=None):
    example = f"""
import requests

url = "https://{{your_server}}{path}"
"""
    if body:
        example += f"payload = {body}\n"

    example += """headers = {"Authorization": "Bearer {your_token}"}
"""

    if method.lower() == 'get':
        example += f"response = requests.get(url, headers=headers)\n"
    elif method.lower() == 'post':
        example += f"response = requests.post(url, headers=headers, json=payload)\n"
    elif method.lower() == 'put':
        example += f"response = requests.put(url, headers=headers, json=payload)\n"
    elif method.lower() == 'patch':
        example += f"response = requests.patch(url, headers=headers, json=payload)\n"
    elif method.lower() == 'delete':
        example += f"response = requests.delete(url, headers=headers)\n"

    example += "print(response.json())\n"
    return example

def custom_openapi(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="OpenMates API",
        version="1.0.0",
        description=(
            "Allows your code to interact with OpenMates server.<br>"
            "<h2>How to get started</h1>"
            "<ol>"
            "<li>Login to your OpenMates account, go to the settings and find your API token there.</li>"
            "<li>Make a request to the endpoint you want to use. Make sure to include your 'token' in the header.</li>"
            "</ol>"
        ),
        routes=app.routes,
        tags=tags_metadata
    )

    # Iterate through all paths and methods
    for path, path_item in openapi_schema["paths"].items():
        for method, operation in path_item.items():
            # Use the predefined example for the body
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("example")
            python_example = generate_python_example(method, path, body=body)

            # Add Python example to the description
            if "description" not in operation:
                operation["description"] = ""
            operation["description"] += f"\n\n**Python Example:**\n```python\n{python_example}\n```"

    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "requestBody", {
        "Example 1": mates_ask_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "responses", {
        "Example 1": task_create_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "get", "responses", {
        "Example 1": mates_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "requestBody", {
        "Example 1": mates_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "responses", {
        "Example 1": mates_create_output_example
    }, "201")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "get", "responses", {
        "Example 1": mates_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "patch", "requestBody", {
        "Example 1": mates_update_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "patch", "responses", {
        "Example 1": mates_update_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "delete", "responses", {
        "Example 1": mates_delete_output_example
    }, "200")
    set_example(openapi_schema, "/v1/teams", "get", "responses", {
        "Example 1": teams_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}", "get", "responses", {
        "Example 1": teams_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/", "get", "responses", {
        "Example 1": users_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}", "get", "responses", {
        "Example 1": users_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/api_token", "patch", "requestBody", {
        "Example 1": users_create_new_api_token_input_example
    })
    set_example(openapi_schema, "/v1/api_token", "patch", "responses", {
        "Example 1": users_create_new_api_token_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}/profile_picture", "patch", "responses", {
        "Example 1": users_replace_profile_picture_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "requestBody", {
        "Example 1": users_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "responses", {
        "Example 1": users_create_output_example
    }, "201")
    set_example(openapi_schema, "/v1/{team_slug}/skills/{software_slug}/{skill_slug}", "get", "responses", {
        "Example 1": skills_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/messages/send", "post", "requestBody", {
        "Example 1": skills_send_message_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/messages/send", "post", "responses", {
        "Example 1": skills_send_message_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/messages/connect", "post", "requestBody", {
        "Example 1": messages_connect_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/messages/connect", "post", "responses", {
        "Example 1": messages_connect_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "requestBody", {
        "Ask question": ai_ask_input_example,
        "Select a tool": ai_ask_input_example_2,
        "Process tool response": ai_ask_input_example_3,
        "Process image": ai_ask_input_example_4,
        "Ask question (stream)": ai_ask_input_example_5
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "responses", {
        "Ask question": ai_ask_output_example,
        "Select a tool": ai_ask_output_example_2,
        "Process tool response": ai_ask_output_example_3,
        "Process image": ai_ask_output_example_4,
    }, "200", "application/json")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "responses", {
        "Stream response": ai_ask_output_example_5
    }, "200", "text/event-stream")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/estimate_cost", "post", "requestBody", {
        "Example 1": ai_estimate_cost_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/estimate_cost", "post", "responses", {
        "Example 1": ai_estimate_cost_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/plan", "post", "requestBody", {
        "Q&A Round 1": code_plan_input_example,
        "Q&A Round 2": code_plan_input_example_2
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/plan", "post", "responses", {
        "Q&A Round 1": code_plan_output_example,
        "Q&A Round 2": code_plan_output_example_2
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/write", "post", "requestBody", {
        "Example 1": code_write_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/write", "post", "responses", {
        "Example 1": code_write_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_report", "post", "requestBody", {
        "Example 1": finance_get_report_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_report", "post", "responses", {
        "Example 1": finance_get_report_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_transactions", "post", "requestBody", {
        "Example 1": finance_get_transactions_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_transactions", "post", "responses", {
        "Example 1": finance_get_transactions_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/docs/create", "post", "requestBody", {
        "Example 1": docs_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/docs/create", "post", "responses", {
        "Example 1": docs_create_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/web/read", "post", "requestBody", {
        "Example 1": web_read_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/web/read", "post", "responses", {
        "Example 1": web_read_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/web/view", "post", "requestBody", {
        "Example 1": web_view_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/web/view", "post", "responses", {
        "Example 1": web_view_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/files/upload", "post", "responses", {
        "Example 1": files_upload_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/files/{provider}/{file_path}", "delete", "responses", {
        "Example 1": files_delete_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/books/translate", "post", "responses", {
        "Example 1": task_create_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/videos/transcript", "post", "requestBody", {
        "Example 1": videos_get_transcript_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/videos/transcript", "post", "responses", {
        "Example 1": videos_get_transcript_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/photos/resize", "post", "responses", {
        "Example 1": photos_resize_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/tasks/{task_id}", "get", "responses", {
        "Example 1": tasks_get_task_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/tasks/{task_id}", "delete", "responses", {
        "Example 1": tasks_cancel_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/billing/get_balance", "get", "requestBody", {
        "Example 1": billing_get_balance_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/billing/get_balance", "post", "responses", {
        "Example 1": billing_get_balance_output_example
    }, "200")


    # Ensure AiAskOutput schema is correctly referenced
    openapi_schema["paths"]["/v1/{team_slug}/skills/ai/ask"]["post"]["responses"]["200"]["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/AiAskOutput"
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def setup_docs(app: FastAPI):
    app.openapi = lambda: custom_openapi(app)

    @app.get("/docs", include_in_schema=False)
    async def custom_api_docs():
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>API Documentation</title>
            <meta charset="utf-8">
            <script type="module" src="https://unpkg.com/rapidoc/dist/rapidoc-min.js"></script>
        </head>
        <body>
            <rapi-doc
                spec-url="/openapi.json"
                header-color="#2d87e2"
                theme="dark"
                show-header="false"
                allow-spec-url-load="false"
                allow-spec-file-load="false"
            > </rapi-doc>
        </body>
        </html>
        """)

    # GET /docs/images/{file_path} (get an image for the docs)
    app.mount("/docs/images", StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'images')), name="images")
