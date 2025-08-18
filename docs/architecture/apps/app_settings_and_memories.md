# App settings and memories

![App settings and memories](../../images/apps/request_app_settings_memories.png)

- as described in [message_processing.md](../message_processing.md), the client submits an overview of the type of app settings and memories that are available
- the assistant then requests the data from the user via websocket connection
- the app settings & memories then show up in chat history as JSON code block. Example:

    ```json
    {
        "app_settings_memories": {
            "included": [
                {
                    "name": "code.favorite_tech",
                    "value": ["Python", "JavaScript", "TypeScript"]
                },
                {
                    "name": "code.current_projects",
                    "value": [{
                        "name": "Sport Team Finder Web App",
                        "description": "A web app to find sports teams and players",
                        "url": "https://github.com/user/sport-team-finder"
                    }]
                }
            ],
            "excluded": [
                "code.past_projects"
            ]
        }
    }
    ```