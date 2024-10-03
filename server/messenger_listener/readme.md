# Workflow

# Setup server (self hosted)
- starts docker compose setup on server via terminal
- will access web interface to continue setup
  - setup AI mates
    - setup which AI mates can be used
      - modify settings like limitations in terms of what software/apps/providers they can use
    - for every AI mate: setup screen for connecting an external messenger (Discord, later also slack, mattermost, telegram and others)
      - for every ai mate, user will be guided throw how to set up an application and bot in discord (or same process for other messengers)
      - once user created an application for that bot, user is asked to enter the application ID
      - based on application ID, a link with needed permissions will be generated, which will be saved in database
      - for every Discord application connected to a team mate, a Discord Listener Docker will be started, that starts waiting for new messages and processes them


# Setup a new team
- user (no admin rights required) creates a new team via web interface
  - set settings and limitations of team (what mates to use, what software/apps/providers to use)
  - in the end, will direct to screen for connecting discord guildes, etc. to OpenMates team
- user will then be asked to create a new user account (that will join the team)
  - incl. preferences / settings


# Join an existing team
- user can join via invite link
- invites can also be limited to certain email addresses
- user will then be asked to create a new user account (that will join the team)
  - incl. preferences / settings


# Invite AI mates to Discord, Slack, etc.
- via webinterface, for a specific team (using team.mates data from GET /api/v1/{team_slug}) a user can see all the mates which are allowed to be connected to external messengers (those which are allowed by team admin)
  - processing for Discord:
    - web interface will show oauth2 links for the mates, for example https://discord.com/oauth2/authorize?client_id={ai_mate_app_client_id}&scope=bot&permissions=377957238848&response_type=code&redirect_uri=https%3A%2F%2Fmywebsite.com%2Fmessenger%2Fconnect
    - ideally: also attach currently open team and the clicked mate to oauth2 url (test if possible)
    - alternative: once a user clicks on a link, a local storage item will be saved, with the current openmates team_id (and clicking another button will be made impossible while the current request isn't finished yet, except for when the user would reload the page, but then also the signin cookie would be deleted)
    - the link will then forward to the web interface, including the guilde_id. For example https://mywebsite.com/messenger/connect?code=EOHm1oOm2pWMNU50yidcnEMv8NNNtC&guild_id=1091750000811740172&permissions=377957238848
    - the web interface (via /messenger/connect) will then show a 'Processing... screen' and save the guilde_id from the URL to the openmates team of the user that is currently selected (read from cookie or local storage) in the loggedin userface of openmates (using POST /api/v1/{team_slug}/apps/messages/connect with data {'discord_guilde_id': guilde_id, 'openmates_team_id': team_id})
    - user repeats the process for every mate he wants to add to his Discord guilde


# Link user account with Discord, Slack, etc.
- via webinterface when viewing user profile (using data from GET /api/v1/{team_slug}/users/{username}), user can see all the "Link to {messenger}" buttons that are available.
  - processing for Discord:
    - web interface will show oauth2 link to connect to OpenMates app, for example: https://discord.com/oauth2/authorize?client_id={openmates_app_client_id}&scope=identify&permissions=0&response_type=code&redirect_uri=https%3A%2F%2Fmywebsite.com%2Fmessenger%2Fconnect
    - the link will then forward to the web interface, including the discord_auth_code. For example https://mywebsite.com/messenger/connect?code=EOHm1oOm2pWMNU50yidcnEMv8NNNtC
    - the web interface (via /messages/connect) will get the origin of the redirect from the header (discord) and will then show a 'Connecting to Discord...' screen and get the user_id from the currently logged in user in openmates and makes a POST /api/v1/{team_slug}/apps/messages/connect with data {'openmates_user_id': user_id,'discord_auth_code': code}, with the 'code' from the url
    - /api/v1/{team_id}/apps/messages/connect will then make a request to the discord api to get the discord api token for the user
    - using the Discord user API token it will get the discord user_id and save it in the user data


# A user sends a message to the Ai team mate via messenger
- processing for Discord:
  - user sends a message to Discord team
  - code checks if the message is mentioning bot directly and is not from the bot itself
  - code gets the openmates team_slug and user_id via API request (POST /api/v1/login with data {'discord_guilde_id': discord_guilde_id, 'discord_user_id': discord_user_id}) from restapi
  - if team with discord_guilde_id or user with discord_user_id cannot be found, respond with "Please connect first the Discord guilde with your team." or "Please connect first your Discord account with your OpenMates account"
  - if discord_guilde_id and discord_user_id found, save them both in Discord listener in memory, so it can be more quickly used next time (seperate redis instance for that?)
  - forward message to /apps/messages/process
    - will load custom user data for specific team and then process message accordingly

