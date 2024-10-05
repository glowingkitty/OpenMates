#!/bin/sh

# Start Uvicorn with the specified port
exec uvicorn container_manager:app --host 0.0.0.0 --port ${CONTAINER_MANAGER_PORT}