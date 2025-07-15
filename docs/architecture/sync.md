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

	
## Opening chat

When a chat is opened, we decrypt the chat and display it in web ui. Maybe we want to consider decrypting all chats in the background and keep them decrypted in memory on client (knowing that we have to redo the decryption probably on page reload?).


## Search

Search feature will be implemented later, covering chats and their content (drafts, messages, files, embedded previews), app settings and memories (also enable optional hiding selected app settings and memories from search), all available settings (and their options). Idea is to also allow quick access to settings as well. All those data are stored in indexeddb. Maybe build search index after all chats and messages are synced.