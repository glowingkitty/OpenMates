#!/bin/bash

set -e

# Parse command line arguments
RESET_FLAG=false
for arg in "$@"; do
  case $arg in
    --reset)
      RESET_FLAG=true
      shift
      ;;
  esac
done

# Function to check if services are already running
check_running_services() {
  # Check if our docker compose services are already running
  if docker compose -f backend/core/core.docker-compose.yml ps --services --filter "status=running" | grep -q "cms"; then
    echo "OpenMates services are already running."
    echo ""
    echo "Options:"
    echo "  1) Continue and start any missing services (recommended)"
    echo "  2) Restart all services"
    echo "  3) Show logs"
    echo "  4) Exit"
    echo ""
    read -p "Please enter your choice (1/2/3/4): " choice
    
    case $choice in
      1)
        echo "Continuing to start any missing services..."
        CONTINUE_WITH_RUNNING_SERVICES=true
        ;;
      2)
        echo "Restarting services..."
        docker compose -f backend/core/core.docker-compose.yml down
        echo "Previous containers stopped. Continuing with restart..."
        CONTINUE_WITH_RUNNING_SERVICES=false
        ;;
      3)
        echo "Showing logs (press Ctrl+C to exit):"
        docker compose -f backend/core/core.docker-compose.yml logs -f
        exit 0
        ;;
      4|*)
        echo "Exiting without changes."
        exit 0
        ;;
    esac
  else
    CONTINUE_WITH_RUNNING_SERVICES=false
  fi
}

# Function to handle database reset
reset_database() {
  echo "⚠️  WARNING: You are about to RESET the database and DELETE ALL DATA! ⚠️"
  echo "This action CANNOT be undone."
  echo ""
  read -p "Type 'DELETE ALL DATA' to confirm reset: " confirmation
  
  if [ "$confirmation" = "DELETE ALL DATA" ]; then
    echo "Confirmation received. Proceeding with database reset..."
    
    echo "Stopping all containers..."
    docker compose -f backend/core/core.docker-compose.yml down
    
    echo "Removing database volume..."
    docker volume rm openmates-postgres-data || true
    
    echo "Database has been reset. Continuing with fresh setup."
    return 0
  else
    echo "Reset operation cancelled. Your data remains intact."
    echo "Continuing with normal startup..."
    return 1
  fi
}

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
  
  # Add API port if it doesn't exist
  if ! grep -q "REST_API_PORT" .env; then
    echo "REST_API_PORT=8000" >> .env
    echo "Added default REST_API_PORT to .env"
  fi
  
  # Add in-memory database port if it doesn't exist
  if ! grep -q "IN_MEMORY_DATABASE_PORT" .env; then
    echo "IN_MEMORY_DATABASE_PORT=6379" >> .env
    echo "Added default IN_MEMORY_DATABASE_PORT to .env"
  fi
  
  # Add server environment setting
  if ! grep -q "SERVER_ENVIRONMENT" .env; then
    echo "SERVER_ENVIRONMENT=development" >> .env
    echo "Added default SERVER_ENVIRONMENT to .env"
  fi
  
  # Add frontend URL for CORS
  if ! grep -q "FRONTEND_URL" .env; then
    echo "FRONTEND_URL=http://localhost:5174" >> .env
    echo "Added default FRONTEND_URL to .env"
  fi
  
  # Ensure the env file is available to Docker Compose
  cp .env backend/core/.env
  echo "Environment variables prepared and copied to backend/core/.env"
}

# Create the OpenMates network if it doesn't exist
setup_network() {
  if (! docker network ls | grep -q "openmates"); then
    echo "Creating OpenMates network..."
    docker network create openmates
  else
    echo "OpenMates network already exists"
  fi

  # Only remove containers if we're not continuing with running services
  if [ "$CONTINUE_WITH_RUNNING_SERVICES" != true ]; then
    # Remove any stale containers that might be causing issues
    echo "Checking for stale containers..."
    if docker ps -a | grep -q "cms-"; then
      echo "Removing any stale containers..."
      docker compose -f backend/core/core.docker-compose.yml down || true
    fi
    
    # Always rebuild the cms-setup container to ensure latest code is used
    echo "Rebuilding cms-setup container to incorporate any code changes..."
    docker compose -f backend/core/core.docker-compose.yml build cms-setup
  else
    echo "Preserving running containers as requested."
  fi
}

# Function to handle database volume compatibility issues
handle_db_volume() {
  # Only check for database volume compatibility if we're not continuing with running services
  if [ "$CONTINUE_WITH_RUNNING_SERVICES" != true ]; then
    echo "Checking for database volume compatibility..."
    
    # Check if volumes exist
    if docker volume ls | grep -q "openmates-postgres-data"; then
      echo ""
      echo "WARNING: Existing database volume detected."
      echo "The error suggests you have an incompatible PostgreSQL version in your volume."
      echo ""
      echo "Options:"
      echo "  1) Remove existing database volume (THIS WILL DELETE ALL DATA)"
      echo "  2) Continue and try to use the existing volume"
      echo ""
      read -p "Please enter your choice (1/2): " choice
      
      if [ "$choice" = "1" ]; then
        echo "Removing existing database volume..."
        docker compose -f backend/core/core.docker-compose.yml down
        docker volume rm openmates-postgres-data
        echo "Database volume removed. A new one will be created."
      else
        echo "Continuing with existing volume. If errors persist, you may need to remove the volume."
      fi
    fi
  fi
}

# Start services
start_services() {
  # Check if we're continuing with running services
  if [ "$CONTINUE_WITH_RUNNING_SERVICES" = true ]; then
    echo "Starting only missing services..."
    
    # Check which services are already running
    RUNNING_SERVICES=$(docker compose -f backend/core/core.docker-compose.yml ps --services --filter "status=running")
    echo "Currently running services: $RUNNING_SERVICES"
    
    # Check if API is already running
    if echo "$RUNNING_SERVICES" | grep -q "api"; then
      echo "API service is already running."
    else
      echo "Starting API service..."
      docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d api
    fi
    
    echo "All required services are now running."
    return 0
  fi
  
  # If we're here, we need to start services from scratch
  echo "Starting Directus database..."
  # Start database first
  docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d cms-database
  
  # Check database logs for errors
  sleep 5
  if docker compose -f backend/core/core.docker-compose.yml logs cms-database | grep -q "FATAL:  database files are incompatible with server"; then
    echo "ERROR: Database version incompatibility detected!"
    docker compose -f backend/core/core.docker-compose.yml down
    handle_db_volume
    echo "Restarting database with compatible settings..."
    docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d cms-database
  fi
  
  echo "Waiting for database to be ready..."
  max_db_retries=20
  db_retry_count=0
  
  while [ $db_retry_count -lt $max_db_retries ]; do
    if docker compose -f backend/core/core.docker-compose.yml --env-file .env exec -T cms-database pg_isready -U directus > /dev/null 2>&1; then
      echo "Database is ready!"
      break
    fi
    echo "Waiting for database to be ready... (attempt $((db_retry_count+1))/$max_db_retries)"
    db_retry_count=$((db_retry_count+1))
    sleep 3
    
    # Check for errors on every 5th attempt
    if [ $((db_retry_count % 5)) -eq 0 ]; then
      if docker compose -f backend/core/core.docker-compose.yml logs cms-database | grep -q "FATAL:"; then
        echo "Database startup errors detected:"
        docker compose -f backend/core/core.docker-compose.yml logs --tail 10 cms-database
        echo "Attempting to fix database compatibility issues..."
        docker compose -f backend/core/core.docker-compose.yml down
        handle_db_volume
        docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d cms-database
      fi
    fi
  done
  
  if [ $db_retry_count -eq $max_db_retries ]; then
    echo "ERROR: Database failed to become ready after $max_db_retries attempts."
    docker compose -f backend/core/core.docker-compose.yml logs cms-database
    exit 1
  fi
  
  echo "Starting Directus CMS..."
  docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d cms
  
  # Give Directus some time to initialize before checking health
  echo "Giving Directus time to initialize (25 seconds)..."
  sleep 25
  
  # Check if Directus is running
  echo "Checking if Directus is running..."
  if curl -s http://localhost:8055 > /dev/null; then
    echo "Directus is reachable. Running schema setup..."
    
    # Check if schemas already exist by checking if invite_codes collection exists
    CHECK_SCHEMA=$(curl -s -H "Authorization: Bearer $(grep CMS_TOKEN .env | cut -d '=' -f2)" \
                  http://localhost:8055/items/invite_codes 2>/dev/null)
    
    if echo "$CHECK_SCHEMA" | grep -q "data"; then
      echo "Schemas already exist. Skipping schema setup."
    else
      echo "Running schema setup using docker-compose defined volumes..."
      docker compose -f backend/core/core.docker-compose.yml --env-file .env run --rm cms-setup
      
      if [ $? -ne 0 ]; then
        echo "Schema setup failed, but Directus is running."
        echo "You can still access Directus at http://localhost:8055"
        echo "Check the logs for more information."
      else
        echo "Schema setup completed successfully."
      fi
    fi
    
    # Start the API service
    echo "Starting API service..."
    docker compose -f backend/core/core.docker-compose.yml --env-file .env up -d api
    
    return 0
  else
    echo "ERROR: Directus is not reachable after initialization period."
    echo "Checking container status:"
    docker compose -f backend/core/core.docker-compose.yml ps
    echo "Check logs for more information:"
    docker compose -f backend/core/core.docker-compose.yml logs cms
    exit 1
  fi
}

# Main execution
echo "===== OpenMates Server Initialization ====="

# Check if services are already running
check_running_services

# Handle reset if flag is present
if [ "$RESET_FLAG" = true ]; then
  reset_database
fi

check_env_file
setup_network
handle_db_volume
start_services

echo "===== Server initialization completed! ====="
echo "Directus admin interface is available at: http://localhost:$(grep CMS_PORT .env | cut -d '=' -f2)"
echo "API is available at: http://localhost:$(grep REST_API_PORT .env | cut -d '=' -f2)"
echo "Admin email: $(grep ADMIN_EMAIL .env | cut -d '=' -f2)"
echo "Admin password: $(grep ADMIN_PASSWORD .env | cut -d '=' -f2)"
echo ""
echo "Check the setup logs for your invite code for the first user!"
echo ""
echo "Usage information:"
echo "  ./start-server.sh         - Start server normally"
echo "  ./start-server.sh --reset - Reset database before starting (deletes all data)"
