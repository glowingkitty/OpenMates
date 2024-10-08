# Installation guide

## Create bots in messengers

### Discord

- visit [https://discord.com/developers/applications](https://discord.com/developers/applications) and login with your Discord account
- for every AI team mate you want to add to the server, create a new Application
  - /General Information:
    - app icon: see profile_image path in [/server.yml](server.yml)
    - name: '{mate name} (OpenMates)' -> 'Sophia (OpenMates)' for example
    - description: see description in [/server.yml](server.yml)
  - /OAuth2:
    - copy client id and paste it to [/.env](.env) under Apps / Messages / Discord into the client_id field for the AI team mate
    - add redirect url: {YOUR_OPENMATES_HOST}/connect/discord (e.g. https://openmates.ai/connect/discord)
  - /Installation:
    - Installation Contexts: Select 'Guild install'
    - Install Link: Select 'Custom' and enter the oauth url:
      - https://discord.com/oauth2/authorize?client_id={client_id}&scope=bot&permissions=311385246784&response_type=code&redirect_uri={redirect_url, url encoded}
    - Also enter the oauth url in [/.env](.env) under Apps / Messages / Discord into the oauth_url field for the AI team mate
  - /Bot:
    - Token: press 'Reset Token' and copy the new token and paste it to [/.env](.env) under Apps / Messages / Discord into the token field for the AI team mate


## Add all missing secrets to .env, based on env.example

## Start Docker Compose