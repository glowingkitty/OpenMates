# Multitasking / Multi agents architecture 

> Stage: idea phase. Not implemented.

For certain more complex tasks it can be beneficial to let multiple agents / chats process a request while keeping one initial chat as an overview / controlling chat for the whole process.

## Usecases

- "implement a search functionality into MyProjectName, to search for chats and settings"
	- main chat would orchestrate
	- would create a separate chat conversation for planning & defining requirements
	- once requirements created, they are given back to original chat
	- new chat is created to check for exisitng code and changes that need to made, with goal of creating a todo.md file
	- once todo file is done, given back to main chat to start separate chats for implementation of various aspects - simultaneous if possible or else after each other
- "create a business plan for my new project"


## How it could work

- mates can start new chats with an initial message from them in the chat, which eithet themself then fullfill or they ask another mate to fullfill the request

### New chat init message

- contains an overview of the context details needed for the request
- contains instructions what to research
- contains completion conditions, which once met will mark the sub task / chat as complete (which will be visible in the original chat and the mate in the original chat can respond accordingly).