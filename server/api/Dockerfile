# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y wget xz-utils libegl1 libopengl0 libxcb-cursor0 portaudio19-dev gcc g++ && \
    wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sh /dev/stdin && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /usr/src/OpenMates/server/api

# Install any needed packages specified in requirements.txt
# Note: You will need to ensure that requirements.txt is available at build time
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# At runtime, the current directory will be mounted, so no need to COPY it

# Copy the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Use the entrypoint script to start Uvicorn
ENTRYPOINT ["/entrypoint.sh"]