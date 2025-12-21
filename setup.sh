#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Function to check if a command is available
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Function to prompt user for yes/no confirmation
prompt_yes_no() {
    local prompt_text="$1"
    local response
    
    while true; do
        read -p "$(echo -e ${YELLOW}${prompt_text}${NC} [y/N]): " response
        case "$response" in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            "" ) return 1;;
            * ) echo "Please answer yes (y) or no (n).";;
        esac
    done
}

# --- Docker and Docker Compose Check ---

check_docker_requirements() {
    local docker_missing=false
    local docker_compose_missing=false
    
    print_info "Checking for Docker and Docker Compose..."
    
    # Check for Docker
    if ! command_exists docker; then
        docker_missing=true
        print_warning "Docker is not installed."
    else
        print_success "Docker is installed."
    fi
    
    # Check for Docker Compose (v2 plugin)
    if ! docker compose version >/dev/null 2>&1; then
        docker_compose_missing=true
        print_warning "Docker Compose plugin is not installed."
    else
        print_success "Docker Compose is installed."
    fi
    
    # If either is missing, prompt for installation
    if [ "$docker_missing" = true ] || [ "$docker_compose_missing" = true ]; then
        echo ""
        print_error "Required dependencies are missing:"
        [ "$docker_missing" = true ] && echo "  - Docker"
        [ "$docker_compose_missing" = true ] && echo "  - Docker Compose"
        echo ""
        print_warning "This script can install Docker and Docker Compose for Debian-based systems (Ubuntu, Debian, etc.)"
        print_warning "The installation requires sudo privileges and will:"
        echo "  - Install Docker using the official Docker installation script"
        echo "  - Install Docker Compose plugin"
        echo "  - Add your user to the docker group (requires logout/login to take effect)"
        echo ""
        
        if ! prompt_yes_no "Do you want to install the missing dependencies now?"; then
            print_error "Setup cancelled. Please install Docker and Docker Compose manually, then run this script again."
            echo ""
            echo "Installation instructions:"
            echo "  - Docker: https://docs.docker.com/get-docker/"
            echo "  - Docker Compose: https://docs.docker.com/compose/install/"
            exit 1
        fi
        
        # Install missing dependencies
        install_docker_dependencies "$docker_missing" "$docker_compose_missing"
    fi
    
    echo ""
}

# Function to install Docker and Docker Compose
install_docker_dependencies() {
    local install_docker=$1
    local install_compose=$2
    
    print_info "Installing missing dependencies..."
  echo ""

    # Check for curl (needed for Docker installation)
  if ! command_exists curl; then
        print_info "Installing curl..."
    sudo apt-get update && sudo apt-get install -y curl
  fi

    # Install Docker if missing
    if [ "$install_docker" = true ]; then
        print_info "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    # Add the current user to the 'docker' group
    sudo usermod -aG docker $USER
        print_success "Docker has been installed."
        print_warning "IMPORTANT: You may need to log out and log back in for the docker group changes to take effect."
        echo ""
    fi
    
    # Install Docker Compose if missing
    if [ "$install_compose" = true ]; then
        print_info "Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
        print_success "Docker Compose has been installed."
        echo ""
    fi
    
    # Verify installations
    if command_exists docker && docker compose version >/dev/null 2>&1; then
        print_success "All Docker dependencies are now installed."
    else
        print_error "Installation verification failed. Please check the installation manually."
        exit 1
    fi
}

# --- Environment Setup ---

# Function to check if .env.example exists
check_env_example() {
    if [ ! -f .env.example ]; then
        print_error ".env.example file not found!"
        echo ""
        echo "The .env.example file is required for setup."
        echo "Please ensure .env.example exists in the project root directory."
        echo ""
        exit 1
    fi
    print_success ".env.example found."
}

# Function to update a variable in the .env file
update_env_var() {
    local var_name=$1
    local var_value=$2
    local temp_file=$(mktemp)

    # Escape pipe character (our sed delimiter) and backslashes in the value
    local escaped_value=$(printf '%s\n' "$var_value" | sed 's/\\/\\\\/g; s/|/\\|/g')
    
    # Check if the variable exists in the file
    if grep -q "^${var_name}=" .env; then
        # Variable exists, update it (using | as delimiter to avoid issues with / in paths)
        sed "s|^${var_name}=.*|${var_name}=${escaped_value}|" .env > "$temp_file" && mv "$temp_file" .env
    else
        # Variable doesn't exist, append it
        echo "${var_name}=${escaped_value}" >> .env
    fi
}

# Function to get value from .env file
get_env_var() {
    local var_name=$1
    if [ -f .env ]; then
        grep "^${var_name}=" .env | cut -d '=' -f2- | sed 's/^"//;s/"$//'
    fi
}

# Function to setup environment file
setup_env_file() {
    print_info "Setting up environment configuration..."
    echo ""
    
    # Check if .env.example exists
    check_env_example
    
    # Create .env from .env.example if it doesn't exist
    if [ ! -f .env ]; then
        print_info "Creating .env file from .env.example..."
        cp .env.example .env
        print_success ".env file created from .env.example."
    else
        print_warning ".env file already exists. Updating with generated secrets..."
        print_info "Note: Existing values will be preserved, only auto-generated secrets will be updated."
    fi
    
    echo ""
    print_info "Generating auto-generated secrets..."
    
    # Helper function to update only if empty or missing
    update_if_empty() {
        local var_name=$1
        local var_value=$2
        local current_value=$(get_env_var "$var_name")
        if [ -z "$current_value" ]; then
            update_env_var "$var_name" "$var_value"
            print_success "Generated ${var_name}"
        else
            print_info "Keeping existing ${var_name}"
        fi
    }
    
    # Generate and set auto-generated secrets (only if empty)
    # Database/Directus admin credentials
    update_if_empty "DATABASE_ADMIN_EMAIL" "admin@example.com"
    update_if_empty "DATABASE_ADMIN_PASSWORD" "$(openssl rand -hex 12)"
    update_if_empty "DATABASE_NAME" "directus"
    update_if_empty "DATABASE_USERNAME" "directus"
    update_if_empty "DATABASE_PASSWORD" "$(openssl rand -hex 12)"
    
    # Directus configuration
    update_if_empty "DIRECTUS_TOKEN" "$(openssl rand -hex 32)"
    update_if_empty "DIRECTUS_SECRET" "$(openssl rand -hex 32)"
    
    # Other services
    update_if_empty "DRAGONFLY_PASSWORD" "$(openssl rand -hex 12)"
    update_if_empty "INTERNAL_API_SHARED_TOKEN" "$(openssl rand -hex 32)"
    
    # Set defaults for optional values if not set
    update_if_empty "CELERY_AUTOSCALE_MAX" "10"
    update_if_empty "CELERY_AUTOSCALE_MIN" "3"
    
    print_success "Auto-generated secrets have been set in .env file."
    echo ""
    
    # Inform user about API keys configuration
    echo "=========================================="
    print_error "⚠️  REQUIRED: API Keys Configuration"
    echo "=========================================="
    echo ""
    print_warning "IMPORTANT: You MUST add at least one AI provider API key before starting the server!"
    print_warning "The server will NOT start successfully without at least one AI provider API key configured."
    echo ""
    print_info "To add API keys, edit the .env file and uncomment/add your keys following the format:"
    echo "  SECRET__{PROVIDER}__API_KEY=your_key_here"
    echo ""
    print_info "Check your .env file for the complete list of available API key variables."
    print_info "Required API keys are marked in the .env file - you must add at least one AI provider key."
    echo ""
    print_warning "⚠️  DO NOT start the server until you have added at least one AI provider API key!"
    echo ""
    
    echo ""
    print_success "Environment configuration complete."
    print_info "You can edit the .env file at any time to add or modify configuration values."
    echo ""
}

# Create the OpenMates network if it doesn't exist
setup_network() {
    print_info "Setting up Docker network..."
    if ! docker network ls | grep -q "openmates"; then
    docker network create openmates
        print_success "Docker network 'openmates' created."
    else
        print_success "Docker network 'openmates' already exists."
    fi
    echo ""
}

# Main execution
main() {
    echo ""
    echo "=========================================="
    echo "  OpenMates Self-Hosted Setup"
    echo "=========================================="
    echo ""
    
    # Step 1: Check Docker requirements
    check_docker_requirements
    
    # Step 2: Setup environment file
    setup_env_file
    
    # Step 3: Setup Docker network
setup_network
    
    # Final instructions
    echo "=========================================="
    print_success "Setup complete!"
    echo "=========================================="
    echo ""
    print_info "Your .env file has been created and configured."
    echo ""
    echo "=========================================="
    print_error "⚠️  CRITICAL: Add API Keys Before Starting"
    echo "=========================================="
    echo ""
    print_warning "BEFORE starting the server, you MUST:"
    echo "  1. Edit the .env file"
    echo "  2. Add at least ONE AI provider API key (see .env file for available options)"
    echo ""
    print_error "The server will NOT start successfully without at least one AI provider API key!"
    print_info "Check your .env file to see which API keys are available and required."
    echo ""
    print_info "After adding your API keys, start OpenMates with:"
    echo ""
    echo -e "  ${GREEN}docker compose --env-file .env -f backend/core/docker-compose.yml up -d${NC}"
    echo ""
    print_info "To also access web UIs (Directus, Grafana), use:"
    echo ""
    echo -e "  ${GREEN}docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d${NC}"
    echo ""
    print_info "After starting, check the logs for your invite code:"
    echo ""
    echo -e "  ${GREEN}docker compose --env-file .env -f backend/core/docker-compose.yml logs cms-setup${NC}"
    echo ""
}

# Run main function
main
