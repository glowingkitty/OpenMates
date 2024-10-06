# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /usr/src/app-messages-discord-listener

# Run discord_listener.py when the container launches
CMD ["python", "discord_listener.py"]