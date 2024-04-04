# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /usr/src/OpenMates

# Set environment variables
ENV STRAPI_URL="http://localhost:1337"

# Install any needed packages specified in requirements.txt
# Note: You will need to ensure that requirements.txt is available at build time
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# At runtime, the server directory will be mounted, so no need to COPY it

# Run the script when the container launches
CMD ["python", "setup.py"]