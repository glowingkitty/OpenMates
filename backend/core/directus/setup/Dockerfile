FROM python:3.10-slim

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && apt-get clean

WORKDIR /usr/src/app

# Copy setup scripts
COPY . .

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml python-dotenv

# Create schemas directory for mounting
RUN mkdir -p /usr/src/app/schemas

# Make script executable
RUN chmod +x setup_schemas.py

# Run setup script
CMD ["python", "setup_schemas.py"]
