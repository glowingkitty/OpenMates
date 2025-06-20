#!/bin/bash

set -e

# Function to check if .env file exists and set required variables
check_env_file() {
  if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
  fi

  # Helper function to update a variable in the .env file if it's empty
  update_env_var_if_empty() {
    local var_name=$1
    local var_value=$2
    # Use a temporary file for sed to ensure compatibility across different systems (macOS/Linux)
    local temp_file=$(mktemp)

    # Check if the variable exists and is empty (e.g., VAR=)
    if grep -q "^${var_name}=$" .env; then
      # It's empty, so set it. Using a different delimiter to handle special chars in password.
      sed "s|^${var_name}=$|${var_name}=${var_value}|" .env > "$temp_file" && mv "$temp_file" .env
      echo "Generated and set ${var_name} in .env"
    fi
  }

  echo "Checking and setting required environment variables..."

  # Set default and generated values for essential services
  update_env_var_if_empty "ADMIN_EMAIL" "admin@example.com"
  update_env_var_if_empty "ADMIN_PASSWORD" "$(openssl rand -base64 12)"
  update_env_var_if_empty "DIRECTUS_TOKEN" "$(openssl rand -hex 32)"
  update_env_var_if_empty "DIRECTUS_SECRET" "$(openssl rand -hex 32)"
  update_env_var_if_empty "DATABASE_PASSWORD" "$(openssl rand -base64 12)"
  update_env_var_if_empty "DRAGONFLY_PASSWORD" "$(openssl rand -base64 12)"
  update_env_var_if_empty "INTERNAL_API_SHARED_TOKEN" "$(openssl rand -hex 32)"

  echo "Environment variables prepared."
}

# Create the OpenMates network if it doesn't exist
setup_network() {
  if (! docker network ls | grep -q "openmates"); then
    echo "Creating OpenMates network..."
    docker network create openmates
  else
    echo "OpenMates network already exists"
  fi
}

echo "===== OpenMates Environment Setup ====="
check_env_file
setup_network
echo ""
echo "Setup complete."
echo "IMPORTANT: Please add your secret API keys to the .env file."
echo ""
echo "You can now start the services using docker compose."
echo "Example: docker compose -f backend/core/docker-compose.yml up -d"
