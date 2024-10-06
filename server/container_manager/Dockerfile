# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /usr/src/app/server/container_manager

# Copy the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Use the entrypoint script to start Uvicorn
ENTRYPOINT ["/entrypoint.sh"]