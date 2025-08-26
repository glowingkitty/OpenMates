# Sync architecture

- on successful login (if lookup hash is included in user entry), warming process starts for user
- get from client also last updated server timestamp to check if or not the local data are already up to date (but this should be only relevant on page reload and not on login, since we delete all user data from indexeddb on logout and if the master key can’t be found in session storage / local storage)


## Warming process

Assuming no memory cached user data yet and assuming no data in indexeddb:
	- load last opened chat (encrypted metadata and chat messages except for last opened timestamp) and all its messages from disk into cache and send via websocket “first chat ready” event (which would send the chat to the new logged in device if it’s already ready to receive data via websocket)
	- chat needs to be decrypted (via aes, only for displaying in the dom. Chat and messages entries in indexeddb remain encrypted) and opened in frontend instantaneously after successfull login
	- then load last 10 updated chats from disk, send to user device which just logged in and store encrypted as is in indexeddb
	- then load all app settings and memories and also store encrypted as is in indexeddb
	- then sync remaining chats and messages from server disk to new device (up to the last 100 chats, encrypted in indexeddb)
	- minimize requests to directus:
		- make sure 'last_opened' field of cached user entry is used to get the chat_id of the last opened chat
		- directus request 1: search for chat entry based on id in directus and return encrypted metadata to frontend for decryption
		- directus request 2 (while processing request 1): search for messages whose 'chat_id' field matches the id of the last opened chat - and return all encrypted messages to frontend for decryption
		- directus request 3: search for 100 last updated chat entries based on timestamp value of 'last_updated' for chats with 'hashed_user_id' based on the hashed user id
		- directus request 4 (after request 3 is completed): search for chat messages whose 'chat_id' field contains any of the chat ids of the last 100 updated chat entries for the user


## Priorities on login

1. Load last opened chat and have it ready as immidiately as possible
2. Load last 10 updated chats and have them synced to the client quickly
3. Load last 100 updated chats and have them synced to the client quickly

## Storage limits and eviction policy (simple)

Goal: Keep the local cache fast and predictable. Sync up to 100 most recent chats (plus last opened and drafts). If local storage would overflow, evict the single oldest cached chat entirely.

- Sync on login
    - Load last opened chat first (full), include current drafts.
    - Then sync up to the 100 most recent chats with both metadata and content into IndexedDB, replacing the local set.

- Eviction on overflow
    - When new messages arrive or syncing a chat would exceed IndexedDB limits, delete the oldest chat in the local set (metadata + messages + embed contents) and retry the write.
    - Oldest chat = least recent by last_updated/last_opened; pinned chats (if supported later) are not considered oldest.

- Older chats on demand
    - When the user scrolls and clicks “Show more”, fetch older messages from the server and keep them in memory only (do not persist them in IndexedDB).
    - If the user sends a message or adds a draft in one of these older chats, it becomes recent and is persisted; to keep the cap, evict the oldest persisted chat if needed.

- Parsing implications
    - Messages use lightweight embed nodes with `contentRef` and minimal metadata; previews are derived at render-time.
    - Full content loads/decrypts on demand in fullscreen. If an evicted `contentRef` is missing locally, fullscreen fetches it on demand or reconstructs from canonical markdown when available.

## Drafts

Drafts are stored on server on disk in the chats model "draft" field.
When a draft is updated on one device, the draft will be send to the server and both distributed to other logged in devices but also saved to the server cache, in case a user device comes online again after network interruption or the user logs in from a new device.
The cached draft is encrypted via the client created wrapped encryption key - making it impossible for the server to read the draft content.
The cached draft auto expires from cache after 2 hours. And once it does so, the chat entry in directus is first updated with the new draft value.
If a draft is deleted (message input field is set to empty and this state is synced to server), we sync that change just as any other draft change - to all devices and to server cache.


	
## Opening chat

When a chat is opened, we decrypt the chat and display it in web ui. Maybe we want to consider decrypting all chats in the background and keep them decrypted in memory on client (knowing that we have to redo the decryption probably on page reload?).


## Search

Search feature will be implemented later, covering chats and their content (drafts, messages, files, embedded previews), app settings and memories (also enable optional hiding selected app settings and memories from search), all available settings (and their options). Idea is to also allow quick access to settings as well. All those data are stored in indexeddb. Maybe build search index after all chats and messages are synced.