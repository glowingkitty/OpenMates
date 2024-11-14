# Server
- integrate ansible and terraform files
- deploy apps.openmates server for testing
- start using plane on server for todo's



# API
- [ ] test discord_listener as seperate docker container first, with hardcoded bot token
- [ ] once receiving messages works, continue with extracting teamslug from message / match request to team/user
  - [ ] on start of the software, check for all users if they have discord connected
    - [ ] then, for every connection, connect to each discord server (but make sure to not have multiple times the same server connected)
    - [ ] start listening to messages
  - [ ] send to mates/ask
  - [ ] process with mates/ask
  - [ ] return response to discord