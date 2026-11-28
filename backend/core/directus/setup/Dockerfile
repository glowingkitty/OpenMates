FROM python:3.13-slim

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && apt-get clean

WORKDIR /usr/src/app

# Copy setup scripts
COPY . .

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml python-dotenv "psycopg[binary]"

# Create schemas directory for mounting
RUN mkdir -p /usr/src/app/schemas

# Make script executable
RUN chmod +x setup_schemas.py

RUN groupadd --gid 10002 cmsschema \
    && useradd --uid 10002 --gid cmsschema --no-create-home --shell /usr/sbin/nologin cmsschema

ENV PYTHONDONTWRITEBYTECODE=1
USER cmsschema

# Run setup script
CMD ["python", "setup_schemas.py"]
