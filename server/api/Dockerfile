# Use an official Python runtime as a parent image
FROM python:3.13-slim

# TODO causes issues with docker build
# # Install dependencies
# RUN apt-get update && \
#     apt-get install -y wget xz-utils libegl1 libopengl0 libxcb-cursor0 portaudio19-dev gcc g++ && \
#     wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sh /dev/stdin && \
#     apt-get clean && \
#     rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /usr/src/app/server/api

# # COPY (for deployment)
# # Copy the server_config.py file
# COPY server_config.py /usr/src/app/server/

# # Copy the server config
# COPY server.yml /usr/src/app/server/

# # Copy the API code
# COPY api/ .

# Install any needed packages specified in requirements.txt
# Note: You will need to ensure that requirements.txt is available at build time
# COPY (for testing)
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
