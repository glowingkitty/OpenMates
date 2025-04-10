# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /usr/src/app

# Run setup_admin.py when the container launches
CMD ["python", "setup_admin.py"]