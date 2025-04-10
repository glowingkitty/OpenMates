FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a directory for persistent data
RUN mkdir -p /app/data

# Copy setup script
COPY setup_vault.py .

# Make script executable
RUN chmod +x setup_vault.py

# Run setup script when container starts
CMD ["python", "setup_vault.py"]
