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

    ##########################################################
    # Mates
    ##########################################################

    # /v1/{team_slug}/mates/ask
    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "requestBody", {
        "Example 1": mates_ask_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "responses", {
        "Example 1": task_create_output_example
    }, "200")
    # /v1/{team_slug}/mates/
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "get", "responses", {
        "Example 1": mates_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "requestBody", {
        "Example 1": mates_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "responses", {
        "Example 1": mates_create_output_example
    }, "201")
    # /v1/{team_slug}/mates/{mate_username}
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


    ##########################################################
    # Teams
    ##########################################################

    # /v1/teams
    set_example(openapi_schema, "/v1/teams", "get", "responses", {
        "Example 1": teams_get_all_output_example
    }, "200")
    # /v1/{team_slug}
    set_example(openapi_schema, "/v1/{team_slug}", "get", "responses", {
        "Example 1": teams_get_one_output_example
    }, "200")


    ##########################################################
    # Users
    ##########################################################

    # /v1/{team_slug}/users/
    set_example(openapi_schema, "/v1/{team_slug}/users/", "get", "responses", {
        "Example 1": users_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "requestBody", {
        "Example 1": users_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "responses", {
        "Example 1": users_create_output_example
    }, "201")
    # /v1/{team_slug}/users/{username}
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}", "get", "responses", {
        "Example 1": users_get_one_output_example
    }, "200")
    # /v1/api_token
    set_example(openapi_schema, "/v1/api_token", "patch", "requestBody", {
        "Example 1": users_create_new_api_token_input_example
    })
    set_example(openapi_schema, "/v1/api_token", "patch", "responses", {
        "Example 1": users_create_new_api_token_output_example
    }, "200")
    # /v1/{team_slug}/users/{username}/profile_picture
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}/profile_picture", "patch", "responses", {
        "Example 1": users_replace_profile_picture_output_example
    }, "200")


    ##########################################################
    # Skills
    ##########################################################

    # will be placed here...


    ##########################################################
    # Tasks
    ##########################################################

    # /v1/{team_slug}/tasks/{task_id}
    set_example(openapi_schema, "/v1/{team_slug}/tasks/{task_id}", "get", "responses", {
        "Example 1": tasks_get_task_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/tasks/{task_id}", "delete", "responses", {
        "Example 1": tasks_cancel_output_example
    }, "200")


    ##########################################################
    # Billing
    ##########################################################

    # /v1/{team_slug}/billing/get_balance
    set_example(openapi_schema, "/v1/{team_slug}/billing/get_balance", "post", "requestBody", {
        "Example 1": billing_get_balance_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/billing/get_balance", "post", "responses", {
        "Example 1": billing_get_balance_output_example
    }, "200")


    ##########################################################
    # Apps
    ##########################################################

    # AI
    # /v1/{team_slug}/apps/ai/ask
    set_example(openapi_schema, "/v1/{team_slug}/apps/ai/ask", "post", "requestBody", {
        "Ask question": ai_ask_input_example,
        "Select a tool": ai_ask_input_example_2,
        "Process tool response": ai_ask_input_example_3,
        "Process image": ai_ask_input_example_4,
        "Ask question (stream)": ai_ask_input_example_5
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/ai/ask", "post", "responses", {
        "Ask question": ai_ask_output_example,
        "Select a tool": ai_ask_output_example_2,
        "Process tool response": ai_ask_output_example_3,
        "Process image": ai_ask_output_example_4,
    }, "200", "application/json")
    set_example(openapi_schema, "/v1/{team_slug}/apps/ai/ask", "post", "responses", {
        "Stream response": ai_ask_output_example_5
    }, "200", "text/event-stream")
    # /v1/{team_slug}/apps/ai/estimate_cost
    set_example(openapi_schema, "/v1/{team_slug}/apps/ai/estimate_cost", "post", "requestBody", {
        "Example 1": ai_estimate_cost_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/ai/estimate_cost", "post", "responses", {
        "Example 1": ai_estimate_cost_output_example
    }, "200")

    # Audio
    # will be placed here...

    # Books
    # /v1/{team_slug}/apps/books/translate
    set_example(openapi_schema, "/v1/{team_slug}/apps/books/translate", "post", "responses", {
        "Example 1": task_create_output_example
    }, "200")

    # Docs
    # /v1/{team_slug}/apps/docs/create
    set_example(openapi_schema, "/v1/{team_slug}/apps/docs/create", "post", "requestBody", {
        "Example 1": docs_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/docs/create", "post", "responses", {
        "Example 1": docs_create_output_example
    }, "200")

    # Files
    # /v1/{team_slug}/files/upload
    set_example(openapi_schema, "/v1/{team_slug}/files/upload", "post", "responses", {
        "Example 1": files_upload_output_example
    }, "200")
    # /v1/{team_slug}/apps/files/{provider}/{file_path}
    set_example(openapi_schema, "/v1/{team_slug}/apps/files/{provider}/{file_path}", "delete", "responses", {
        "Example 1": files_delete_output_example
    }, "200")

    # Finance
    # /v1/{team_slug}/apps/finance/get_report
    set_example(openapi_schema, "/v1/{team_slug}/apps/finance/get_report", "post", "requestBody", {
        "Example 1": finance_get_report_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/finance/get_report", "post", "responses", {
        "Example 1": finance_get_report_output_example
    }, "200")
    # /v1/{team_slug}/apps/finance/get_transactions
    set_example(openapi_schema, "/v1/{team_slug}/apps/finance/get_transactions", "post", "requestBody", {
        "Example 1": finance_get_transactions_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/finance/get_transactions", "post", "responses", {
        "Example 1": finance_get_transactions_output_example
    }, "200")

    # Health
    # /v1/{team_slug}/apps/health/search_doctors
    set_example(openapi_schema, "/v1/{team_slug}/apps/health/search_doctors", "post", "requestBody", {
        "Example 1": health_search_doctors_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/health/search_doctors", "post", "responses", {
        "Example 1": health_search_doctors_output_example
    }, "200")
    # /v1/{team_slug}/apps/health/search_appointments
    set_example(openapi_schema, "/v1/{team_slug}/apps/health/search_appointments", "post", "requestBody", {
        "Example 1": health_search_appointments_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/health/search_appointments", "post", "responses", {
        "Example 1": health_search_appointments_output_example
    }, "200")

    # Home
    # /v1/{team_slug}/apps/home/get_all_devices
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_all_devices", "post", "requestBody", {
        "Example 1": home_get_all_devices_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_all_devices", "post", "responses", {
        "Example 1": home_get_all_devices_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/get_all_scenes
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_all_scenes", "post", "requestBody", {
        "Example 1": home_get_all_scenes_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_all_scenes", "post", "responses", {
        "Example 1": home_get_all_scenes_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/get_temperature
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_temperature", "post", "requestBody", {
        "Example 1": home_get_temperature_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_temperature", "post", "responses", {
        "Example 1": home_get_temperature_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/add_device
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/add_device", "post", "requestBody", {
        "Example 1": home_add_device_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/add_device", "post", "responses", {
        "Example 1": home_add_device_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/add_scene
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/add_scene", "post", "requestBody", {
        "Example 1": home_add_scene_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/add_scene", "post", "responses", {
        "Example 1": home_add_scene_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/set_device
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/set_device", "post", "requestBody", {
        "Example 1": home_set_device_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/set_device", "post", "responses", {
        "Example 1": home_set_device_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/set_scene
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/set_scene", "post", "requestBody", {
        "Example 1": home_set_scene_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/set_scene", "post", "responses", {
        "Example 1": home_set_scene_output_example
    }, "200")
    # /v1/{team_slug}/apps/home/get_power_consumption
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_power_consumption", "post", "requestBody", {
        "Example 1": home_get_power_consumption_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/home/get_power_consumption", "post", "responses", {
        "Example 1": home_get_power_consumption_output_example
    }, "200")

    # Maps
    # /v1/{team_slug}/apps/maps/search
    set_example(openapi_schema, "/v1/{team_slug}/apps/maps/search", "post", "requestBody", {
        "Example 1": maps_search_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/maps/search", "post", "responses", {
        "Example 1": maps_search_output_example
    }, "200")

    # Messages
    # /v1/{team_slug}/apps/messages/send
    set_example(openapi_schema, "/v1/{team_slug}/apps/messages/send", "post", "requestBody", {
        "Example 1": skills_send_message_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/messages/send", "post", "responses", {
        "Example 1": skills_send_message_output_example
    }, "200")
    # /v1/{team_slug}/apps/messages/connect
    set_example(openapi_schema, "/v1/{team_slug}/apps/messages/connect", "post", "requestBody", {
        "Example 1": messages_connect_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/messages/connect", "post", "responses", {
        "Example 1": messages_connect_output_example
    }, "200")

    # PDF Editor
    # will be placed here...

    # Photos
    # /v1/{team_slug}/apps/photos/resize
    set_example(openapi_schema, "/v1/{team_slug}/apps/photos/resize", "post", "responses", {
        "Example 1": photos_resize_output_example
    }, "200")

    # Travel
    # /v1/{team_slug}/apps/travel/search_connections
    set_example(openapi_schema, "/v1/{team_slug}/apps/travel/search_connections", "post", "requestBody", {
        "Example 1": travel_search_connections_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/travel/search_connections", "post", "responses", {
        "Example 1": travel_search_connections_output_example
    }, "200")

    # Videos
    # /v1/{team_slug}/apps/videos/transcript
    set_example(openapi_schema, "/v1/{team_slug}/apps/videos/transcript", "post", "requestBody", {
        "Example 1": videos_get_transcript_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/videos/transcript", "post", "responses", {
        "Example 1": videos_get_transcript_output_example
    }, "200")

    # Web
    # /v1/{team_slug}/apps/web/read
    set_example(openapi_schema, "/v1/{team_slug}/apps/web/read", "post", "requestBody", {
        "Example 1": web_read_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/web/read", "post", "responses", {
        "Example 1": web_read_output_example
    }, "200")
    # /v1/{team_slug}/apps/web/view
    set_example(openapi_schema, "/v1/{team_slug}/apps/web/view", "post", "requestBody", {
        "Example 1": web_view_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/apps/web/view", "post", "responses", {
        "Example 1": web_view_output_example
    }, "200")

    # Ensure AiAskOutput schema is correctly referenced
    openapi_schema["paths"]["/v1/{team_slug}/apps/ai/ask"]["post"]["responses"]["200"]["content"]["application/json"]["schema"] = {
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
            <style>
                rapi-doc {
                    max-width: 100%;
                }
                rapi-doc::part(section-operation-response),
                rapi-doc::part(section-request-body),
                rapi-doc::part(section-response-body),
                rapi-doc::part(section-response-headers) {
                    white-space: normal !important;
                    word-wrap: break-word !important;
                    overflow-wrap: break-word !important;
                    max-width: 100% !important;
                    overflow: auto; /* Allow scrolling if necessary */
                }
                rapi-doc::part(textarea) {
                    white-space: pre-wrap !important;
                    word-wrap: break-word !important;
                    overflow-wrap: break-word !important;
                }
                /* Additional rule for response content */
                rapi-doc::part(section-response-body) {
                    max-height: 300px; /* Set a max height for the response area */
                    overflow-y: auto; /* Enable vertical scrolling */
                }
            </style>
        </head>
        <body>
            <rapi-doc
                spec-url="/openapi.json"
                header-color="#2d87e2"
                theme="dark"
                show-header="false"
                allow-spec-url-load="false"
                allow-spec-file-load="false"
                render-style="read"
            > </rapi-doc>
        </body>
        </html>
        """)

    # GET /images/{file_path} (get an image for the docs)
    app.mount("/images", StaticFiles(directory=os.path.join(os.path.dirname(__file__), '../images')), name="images")
