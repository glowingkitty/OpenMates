# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install dependencies
COPY apps/messages/discord/listener/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /usr/src/app

# Copy only the necessary files
COPY apps/messages/discord/listener /usr/src/app
COPY server.yml /usr/src/app/server.yml
COPY server_config.py /usr/src/app/server_config.py

# Run discord_listener.py when the container launches
CMD ["python", "discord_listener.py"]
