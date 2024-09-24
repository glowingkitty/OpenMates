#!/bin/sh

# Start Uvicorn with the specified port
exec uvicorn web_browser:app --host 0.0.0.0 --port ${WEB_BROWSER_PORT}