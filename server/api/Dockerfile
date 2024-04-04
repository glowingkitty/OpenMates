# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /usr/src/OpenMates/server/api

# Install any needed packages specified in requirements.txt
# Note: You will need to ensure that requirements.txt is available at build time
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# At runtime, the current directory will be mounted, so no need to COPY it

# Run api.py when the container launches
CMD ["python", "api.py"]