#!/bin/sh

# Start Uvicorn with the specified port
exec uvicorn api:app --host 0.0.0.0 --port ${REST_API_PORT}