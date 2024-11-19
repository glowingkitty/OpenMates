# OpenMates Self Hosted Edition

## Server infrastructure

OpenMates is designed to be deployed on multiple separated servers (for performance & security reasons), but optionally can run on a single device (only recommended for running it locally on your device).

![Server Infrastructure Diagram](./diagrams/server_architecture.drawio.svg)

## Server setup

### 1. .env file
Create an [../.env](../.env) file (in the server folder) based on the env.example [../env.example](../env.example).
CMS secrets will be automatically added later.

### 2. Setup bots
Setup the bots that make sure users can chat with OpenMates via external apps (Discord, Mattermost, Element, Slack, Telegram, etc.).

#### Discord

- visit [https://discord.com/developers/applications](https://discord.com/developers/applications) and login with your Discord account
- for every AI team mate you want to add to the server, create a new Application
  - /General Information:
    - app icon: see profile_image path in [../api/configs/mates/mates.yml](../api/configs/mates/mates.yml)
    - name: '{mate name} (OpenMates)' -> 'Sophia (OpenMates)' for example
    - description: see description in [../api/configs/mates/mates.yml](../api/configs/mates/mates.yml)
  - /OAuth2:
    - copy client id and paste it to [../.env](../.env) under Apps / Messages / Discord into the client_id field for the AI team mate
    - add redirect url: {YOUR_OPENMATES_HOST}/connect/discord (e.g. https://openmates.org/connect/discord)
  - /Installation:
    - Installation Contexts: Select 'Guild install'
    - Install Link: Select 'Custom' and enter the oauth url:
      - https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=311385246784&response_type=code&redirect_uri={redirect_url, url encoded}
    - Also enter the oauth url in [../.env](../.env) under Apps / Messages / Discord into the oauth_url field for the AI team mate
  - /Bot:
    - Token: press 'Reset Token' and copy the new token and paste it to [../.env](../.env) under Apps / Messages / Discord into the token field for the AI team mate
- in the [../.env](../.env) enter all bot secrets under the "# 'Messages' app" part

### 3. Check apps to install
(ignore this if you only install the core services)
Check the [../.env](../.env) 

### 2. ./setup.sh
Start ./setup.sh script and follow the process or execute with input commands for automated setup:

| Option | Description |
|--------|-------------|
| `--setup-core` | Setup a server with all core services. |
| `--setup-apps` | Setup a server with all apps. |
| `--setup-full` | Setup a server with both the core services and the apps setup (Only recommended for running on local device, not recommended for server deployment, for security & performance reasons). |

### Setup overview
![Server Setup Diagram](./diagrams/server_setup.drawio.svg)