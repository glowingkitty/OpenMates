FROM python:3.10-slim

# Install curl for health checks and making HTTP requests
RUN apt-get update && apt-get install -y curl && apt-get clean

WORKDIR /usr/src/app

# Copy setup scripts
COPY . .

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml python-dotenv

# Add a script to check if Directus is reachable
RUN echo '#!/bin/sh\ncurl -s -o /dev/null -w "%{http_code}" http://cms:8055/' > /usr/local/bin/check-directus.sh && \
    chmod +x /usr/local/bin/check-directus.sh

# Make script executable
RUN chmod +x setup_schemas.py

# Run setup script
CMD ["python", "setup_schemas.py"]
