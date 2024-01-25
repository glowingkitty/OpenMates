# Auto code generation & testing

- send a message to Sophia bot, asking to create & test code to do XY
- Sophia will create a plan what to do (goal, steps what the code should do, what packages or APIs to use)
- Sophia will ask for a confirmation
- once confirmed, code will be written for all the files, a docker file and the container.json file
- a new repo will be created and the code will be pushed
- the codespace will be started, the code executed
- if an error in the executed code occures, user will be informed via chat and bot will debug the code and try again (if 5 times in a row an error occured, the user will be asked what to do next and help out)
- user has always the option to open the codespace and interrupt the auto debugging process
- once the code is successfull and doesn't crash, the terminal output will be returned to chat and the correctly working code will be pushed to git repo
- 

## Needed functions

### Codespaces
- create_codespace
- stop_codespace
  
### Repositories
- create_repo
- get_repos

## Questions
- how to start code? via dockerfile / container json?