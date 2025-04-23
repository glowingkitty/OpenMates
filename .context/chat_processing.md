# Processing

- user starts writing a message
- every time the user stops for longer than x ms, frontend makes a request to /chats/draft with optionally the ID of the chat. backend will then either update the cached draft of the existing chat or if no chat exists yet it, it creates a new chat in cache (make sure the id can be generated in a way that reliable creates unique IDs even without checking directus. maybe based on user id and then longer chat id)
- user sends message to chatbot: frontend makes request to /chat/send with the chat id (if it exists already). backend will then check in cache if message history exists for chat. if yes, loads that and sends chat to /apps/ai/preprocess (of course after checking that user is allowed to make the request / is authentificated). Else sends the new single message to preprocessing (meaning, sending the request to separate ai app docker, via celery)
- /apps
- chats saved encrypted in cache (using AES-GCM Encryption/Decryption), but instead of connected to user id they are connected to user id hash
- chats saved encrypted in directus (but in a way that even decrypting 100.000 words would only take max 2-3 seconds)


# Activityhistory
- use multiplexing websocket system (one websocket connection per device, secure, via wss://!) to:
    - sync the currently open chat in real time (when messages are received: paragraph by paragraph)
    - sync currently active chats in background which receive data only when a new message has been received in full
    - sync the list of chats, if new chats are added, old deleted, headlines changed, folders created, chats get hidden, etc.

# Preprocessing chat message

## Goals of preprocessing
- filter out and reject harmful or illegal requests (use suspicion level and inform LLM if the level is considered elevated: example - user asks about hacking, which might be harmful, maybe not depending on context)
- forward message to best fitting mate depending on topic
- detect complexity level of request to maximize cost / performance balance for user
- detect if full conversation should be included or if last 2 messages are enough or only new message
- detect what temperature level makes the most sense (from 0.0 to 1.0, from not creative at all, to very creative)

## Output structure example
```json
{
    "mate": "sophia",
    "difficulty": "complex",
    "harmful_risk_level": 2,
    "message_history": "full",
    "temperature": 0.4
}
```

# Main processing
- python script will then process the output 