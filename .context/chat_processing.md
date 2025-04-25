# Draft processing:

- user clicks on the message input field/selects it
- a random unique id is generated and saved in memory
- user starts writing a message
- every time the user stops for longer than 700 ms (or clicks somewhere outside the message input field or events like beforeunload or visibilitychange), frontend checks if draft content has changed and if so sends via existing websocket connection data to the backend with the unique draft id that we generated (which is saved together with the chat metadata also in indexeddb), to update the draft (both on the server, but also save the draft content in indexeddb)
- if the id already exists, then update the draft content (the text, encrypted using AES-GCM), else create the new draft with the encrypted text


# Activityhistory
- use multiplexing websocket system (one websocket connection per device, secure, via wss://!) to:
    - sync the currently open chat in real time (when LLM response is currently received: update response message on every update - backend will make sure we only send updates paragraph by paragraph, instead of word by word)
    - sync currently active chats in background which receive data only when a new message has been received in full
    - sync the list of chats, if new chats are added, old deleted, headlines changed, folders created, chats get hidden, etc.
    - sync drafts
- websocket connection uses same user validation as other api endpoints (making sure the user is logged in and device fingerprint hash is known for the user, else refuse connection)
- if connection breaks (because user starts vpn for example and therefore ip changes), system will do the same auth check, noticing that the device fingerprint hash has changed and therefore require entering a 2fa otp code to continue session (to protect against auth token being stolen by browser extensions for example)
- Use versioning to prevent sync conflicts, for drafts, updates to chat titles, chat settings 
    - When a draft is created or loaded, the server includes a version number (e.g., _v: 1).
    - Client stores the draft content and its version number (_v: 1).
    - User edits the draft.
    - Client sends the update via WebSocket: { type: 'draft_update', payload: { chatId: '...', draftId: '...', content: 'new content', basedOnVersion: 1 } }
    - Server receives the update:
        - It fetches the current draft version from Dragonfly (let's say it's still _v: 1).
        - It compares incoming.basedOnVersion (1) with the stored version (1). They match!
        - Server increments the version (_v: 2), saves the "new content" and the new version _v: 2 to Dragonfly.
        - Server sends a confirmation/broadcast back (optional but good): { type: 'draft_updated', payload: { chatId: '...', draftId: '...', content: 'new content', version: 2 } }
    - Offline Scenario with Versioning:
        - Client A has draft "v1", _v: 1. Goes offline.
        - Client B updates to "v2", sends basedOnVersion: 1. Server accepts, saves "v2", _v: 2.
        - Client A comes online. Sends its stale "v1" update with basedOnVersion: 1.
        - Server receives it. Fetches current draft: "v2", _v: 2.
        - Compares incoming.basedOnVersion (1) with stored version (2). They don't match!
        - Server rejects the update from Client A (e.g., sends back an error message { type: 'draft_conflict', payload: { chatId: '...', draftId: '...' } }).
        - Client A receives the rejection. It should now discard its local stale changes and fetch the latest version ("v2", _v: 2) from the server before allowing the user to edit again.
- chats are saved / synced decrypted to indexeddb for offline access and faster load times
- we also save separate the decrypted activityhistory (with the headlines/details of all chats, but without the content) for all chats.
- load priority:
    1. Phase 1: load last opened chat (metadata for activityhistory + content: text + S3 low resolution image previews for images, web thumbnails, video thumbnails, so user can directly continue where they left off)
    2. Phase 2: load most recently viewed chats 2 - 20 (metadata for activityhistory only, so user can see most recent chats and it feels like they are already loaded)
    3. Phase 3: load most recently viewed chats 2 - 20 (content: text + S3 images, so they can be clicked on and content is directly there)
    4. Phase 4: load batches of 20 chats (metadata for activityhistory only), until all most recent 1000 chats are loaded
    3. Phase 4: load batches of 20 chats (text + S3 images), until all most recent 1000 chats are loaded (but max 5MB of low res images of most recently opened chats)
- when the user clicks on another chat, we load the chat from indexeddb (or prioritze it in websocket connection, if its not yet offline downloaded)
- we limit the amount of offline downloaded chats to the last 1000 most recent chats and render by default only the 20 most recent chats (and user can scroll to see older messages or up again to see more recent messages). Keep in mind this needs to still work even if the user scrolls wayy down to for example chat 480 of 1000 - and we don't want 480 chats still rendered in the dom, but only those that are currently in viewport visible plus a few more for better smooth loading experience.
- low res images are limited to 5MB total size for all images (the 500 images in the most recent chats)

# Message send to server:
- if new chat is started, server will create an encryption key per chat, which is used for storing encrypted chats in memory (dragonfly) and storage (directus) on server
- save encryption key in hashicorp vault and save key id in memory/directus?
- when frontend syncs via websocket to backend it receives the decrypted chats

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


<!-- Later, not today... -->
# Search
- implement FlexSearch later for fast search inside chats and settings (and index via webworker and store index in indexeddb)