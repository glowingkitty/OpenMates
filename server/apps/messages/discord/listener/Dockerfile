# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /usr/src/OpenMates/server/apps/messages/discord

# Copy the requirements file into the container
COPY server/apps/messages/discord/requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# At runtime, the current directory will be mounted, so no need to COPY it

# Run discord_listener.py when the container launches
CMD ["python", "discord_listener.py"]