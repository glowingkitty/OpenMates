FROM python:3.10-slim

# Install curl, wget and other troubleshooting tools
RUN apt-get update && apt-get install -y curl wget iputils-ping net-tools dnsutils && apt-get clean

WORKDIR /usr/src/app

# Copy setup scripts
COPY . .

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml python-dotenv

# Make script executable
RUN chmod +x setup_schemas.py

# Run setup script
CMD ["python", "setup_schemas.py"]
