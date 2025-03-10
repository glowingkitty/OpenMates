#!/bin/bash

set -e

# Function to check if .env file exists and contains the required variables
check_env_file() {
  if [ ! -f .env ]; then
    echo "Creating .env file with default values..."
    touch .env
  fi

  # Check and set Directus admin credentials if they don't exist
  if ! grep -q "ADMIN_EMAIL" .env; then
    echo "ADMIN_EMAIL=admin@example.com" >> .env
    echo "Added default ADMIN_EMAIL to .env"
  fi

  if ! grep -q "ADMIN_PASSWORD" .env; then
    random_password=$(openssl rand -base64 12)
    echo "ADMIN_PASSWORD=${random_password}" >> .env
    echo "Added random ADMIN_PASSWORD to .env"
  fi

  if ! grep -q "CMS_TOKEN" .env; then
    cms_token=$(openssl rand -hex 32)
    echo "CMS_TOKEN=${cms_token}" >> .env
    echo "Added random CMS_TOKEN to .env"
  fi
  
  if ! grep -q "ADMIN_JWT_SECRET" .env; then
    jwt_secret=$(openssl rand -hex 32)
    echo "ADMIN_JWT_SECRET=${jwt_secret}" >> .env
    echo "Added random ADMIN_JWT_SECRET to .env"
  fi

  if ! grep -q "JWT_SECRET" .env; then
    jwt_secret=$(openssl rand -hex 32)
    echo "JWT_SECRET=${jwt_secret}" >> .env
    echo "Added random JWT_SECRET to .env"
  fi

  # Set database connection parameters
  if ! grep -q "DATABASE_PORT" .env; then
    echo "DATABASE_PORT=5432" >> .env
  fi

  if ! grep -q "DATABASE_NAME" .env; then
    echo "DATABASE_NAME=directus" >> .env
  fi

  if ! grep -q "DATABASE_USERNAME" .env; then
    echo "DATABASE_USERNAME=directus" >> .env
  fi

  if ! grep -q "DATABASE_PASSWORD" .env; then
    db_password=$(openssl rand -base64 12)
    echo "DATABASE_PASSWORD=${db_password}" >> .env
    echo "Added random DATABASE_PASSWORD to .env"
  fi

  if ! grep -q "CMS_PORT" .env; then
    echo "CMS_PORT=8055" >> .env
  fi

  if ! grep -q "SERVER_HOST" .env; then
    echo "SERVER_HOST=0.0.0.0" >> .env
  fi
}

# Create the OpenMates network if it doesn't exist
setup_network() {
  if ! docker network ls | grep -q openmates; then
    echo "Creating OpenMates network..."
    docker network create openmates
  fi
}

# Start Directus and run schema setup
start_services() {
  echo "Starting Directus and related services..."
  docker compose -f backend/core/core.docker-compose.yml up -d cms cms-database
  
  # Wait for Directus to be healthy
  echo "Waiting for Directus to become healthy..."
  while ! docker compose -f backend/core/core.docker-compose.yml exec -T cms curl -s http://localhost:8055/server/health | grep -q "ok"; do
    echo "Waiting for Directus health check..."
    sleep 5
  done
  
  echo "Directus is ready. Running schema setup..."
  docker compose -f backend/core/core.docker-compose.yml up cms-setup
}

# Main execution
echo "===== OpenMates Server Initialization ====="
check_env_file
setup_network
start_services

echo "===== Server initialization completed! ====="
echo "Directus admin interface is available at: http://localhost:$(grep CMS_PORT .env | cut -d '=' -f2)"
echo "Admin email: $(grep ADMIN_EMAIL .env | cut -d '=' -f2)"
echo "Admin password: $(grep ADMIN_PASSWORD .env | cut -d '=' -f2)"
echo ""
echo "Check the setup logs for your invite code for the first user!"
