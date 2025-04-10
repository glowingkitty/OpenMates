# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Install dependencies
COPY apps/messages/discord/listener/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /usr/src/app

# Copy only the necessary files
COPY apps/messages/discord/listener /usr/src/app
COPY server.yml /usr/src/app/server.yml
COPY api/configs/apps/messages/app.yml /usr/src/app/api/configs/apps/messages/app.yml
COPY server_config.py /usr/src/app/server_config.py