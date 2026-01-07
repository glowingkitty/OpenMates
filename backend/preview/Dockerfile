# OpenMates Preview Server Dockerfile
# 
# Lightweight image for proxying and caching images/favicons
# and extracting URL metadata (Open Graph).
#
# Build:
#   docker build -t openmates-preview .
#
# Run:
#   docker run -p 8080:8080 -v preview-cache:/app/cache openmates-preview

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    # Preview server defaults
    PREVIEW_HOST=0.0.0.0 \
    PREVIEW_PORT=8080 \
    PREVIEW_ENVIRONMENT=production \
    PREVIEW_DEBUG=false \
    PREVIEW_CACHE_DIR=/app/cache \
    PREVIEW_LOG_LEVEL=INFO

# Create non-root user for security
RUN groupadd --gid 1000 preview && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home preview

# Install system dependencies
# - libxml2/libxslt for lxml (HTML parsing)
# - libjpeg/zlib for Pillow (image processing)
# - curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt1-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libwebp-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create cache directory with correct permissions
RUN mkdir -p /app/cache && \
    chown -R preview:preview /app

# Switch to non-root user
USER preview

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application with multiple workers for concurrent image processing
# Workers configurable via UVICORN_WORKERS env var (default: 4)
# Each worker can process 1 image at a time, so 4 workers = 4 concurrent image processing
CMD sh -c "python -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${UVICORN_WORKERS:-4}"

