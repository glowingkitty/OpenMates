# Processing

- user starts writing a message
- every time the user stops for longer than x ms, frontend makes a request to /chats/draft with optionally the ID of the chat. backend will then either update the cached draft of the existing chat or if no chat exists yet it, it creates a new chat in cache (make sure the id can be generated in a way that reliable creates unique IDs even without checking directus. maybe based on user id and then longer chat id)
- user sends message to chatbot: frontend makes request to /chat/send with the chat id (if it exists already). backend will then check in cache if message history exists for chat. if yes, loads that and sends chat to /apps/ai/preprocess (of course after checking that user is allowed to make the request / is authentificated). Else sends the new single message to preprocessing (meaning, sending the request to separate ai app docker, via celery)
- /apps