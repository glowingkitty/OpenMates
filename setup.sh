#!/bin/bash

set -e

# --- Dependency Installation ---

# Function to check if a command is available
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Function to install dependencies if they are missing
install_dependencies() {
  echo "Checking and installing required dependencies..."
  echo "This script is designed for Debian-based Linux distributions (e.g., Ubuntu) and requires sudo for installation."
  echo "If you are on a different OS, please install Docker, Docker Compose, Node.js, and pnpm manually."
  echo ""

  # Check for curl, as it's needed for installers
  if ! command_exists curl; then
    echo "curl not found. Attempting to install..."
    sudo apt-get update && sudo apt-get install -y curl
  fi

  # Check for Docker
  if ! command_exists docker; then
    echo "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    # Add the current user to the 'docker' group
    sudo usermod -aG docker $USER
    echo "Docker has been installed. IMPORTANT: You may need to log out and log back in for the group changes to take effect."
  else
    echo "Docker is already installed."
  fi

  # Check for Docker Compose (v2 plugin)
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose plugin not found. Installing..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
  else
    echo "Docker Compose is already installed."
  fi

  # Check for Node.js and npm
  if ! command_exists node || ! command_exists npm; then
    echo "Node.js or npm not found. Installing Node.js and npm..."
    # Using NodeSource repository for a recent version of Node.js
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
  else
    echo "Node.js and npm are already installed."
  fi

  # Check for pnpm
  if ! command_exists pnpm; then
    echo "pnpm not found. Installing pnpm globally via npm..."
    sudo npm install -g pnpm
    echo "pnpm has been installed."
  else
    echo "pnpm is already installed."
  fi

  echo ""
  echo "Dependency check complete."
  echo "----------------------------------------"
}


# --- Environment Setup ---

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
install_dependencies
check_env_file
setup_network
echo ""
echo "Setup complete."
echo "IMPORTANT: Please add your secret API keys to the .env file."
echo ""
echo "You can now start the services using docker compose."
echo "Example: docker compose --env-file .env -f backend/core/docker-compose.yml up -d"
