#!/bin/bash


# TODO script is just a draft. Make it work better.
# TODO ask the user to update the .env file and once done, user should enter 'Done' and press enter
# TODO once .env file is updated, start the docker compose setup

# Function to print messages in bold
bold() {
    tput bold
    echo "$1"
    tput sgr0
}

# Function to print messages in color
color() {
    tput setaf "$1"
    echo "$2"
    tput sgr0
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    color 1 "Docker is not installed. Please install Docker first."
    exit 1
else
    bold "Docker is installed."
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    color 1 "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
else
    bold "Docker Compose is installed."
fi



# Function to print the ASCII art logo
print_logo() {
    cat << "EOF"
     _____________________________________________________________________
    |                                                                     |
    |         ____                  __  __        _                       |
    |        / __ \                |  \/   |     | |                      |
    |       | |  | |_ __   ___ _ __| \  /  | __ _| |_ ___  ___            |
    |       | |  | | '_ \ / _ \ '_ \ |\/ | |/ _` | __/ _ \/ __|           |
    |       | |__| | |_) |  __/ | | | |  | | (_| | ||  __/\__ \           |
    |        \____/| .__/ \___|_| |_|_|  |_|\__,_|\__\___||___/           |
    |              | |                                                    |
    |              |_|                                                    |
    |                                                                     |
    |_____________________________________________________________________|
                          Your AI team mates.
EOF
}

# Welcome message
bold "Welcome to the OpenMates installation script."

# Call the function to print the logo
print_logo

# Prompt for which apps to install
color 3 "Which apps would you like to install? (e.g., app-web, rest-api)"
read -p "Enter app names separated by spaces: " apps

# Create or update the .env file
bold "Creating .env file..."
cat <<EOL > .env
# Add your environment variables here
WEB_BROWSER_PORT=8080
REST_API_PORT=5000
# Add more default variables as needed
EOL

# Modify docker-compose.yml based on user input
bold "Configuring docker-compose.yml..."
for app in $apps; do
    # Uncomment the selected apps
    sed -i '' "/# $app:/,/^$/s/^# //" server/docker-compose.yml
done

# Comment out apps not selected
all_apps=("app-web" "rest-api" "app-home-mosquitto" "task-worker")
for app in "${all_apps[@]}"; do
    if [[ ! " ${apps[@]} " =~ " ${app} " ]]; then
        # Comment out the unselected apps
        sed -i '' "/$app:/,/^$/s/^/# /" server/docker-compose.yml
    fi
done

bold "Configuration complete. Please add your API keys and other sensitive information to the .env file."

color 2 "To start the Docker Compose setup, run: docker-compose up -d"

bold "Installation script finished."
