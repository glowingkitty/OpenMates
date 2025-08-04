# Symc architecture

- on successful login (if lookup hash is included in user entry), warming process starts for user
- get from client also last updated server timestamp to check if or not the local data are already up to date (but this should be only relevant on page reload and not on login, since we delete all user data from indexeddb on logout and if the master key can’t be found in session storage / local storage)


## warming process

Assuming no memory cached user data yet and assuming no data in indexeddb:
	- load last opened chat (encrypted metadata and chat messages except for last opened timestamp) and all its messages from disk into cache and send via websocket “first chat ready” event (which would send the chat to the new logged in device if it’s already ready to receive data via websocket)
	- chat needs to be decrypted (via aes, only for displaying in the dom. Chat and messages entries in indexeddb remain encrypted) and opened in frontend instantaneously after successfull login
	- then load last 10 updated chats from disk, send to user device which just logged in and store encrypted as is in indexeddb
	- then load all app settings and memories and also store encrypted as is in indexeddb
	- then sync remaining chats and messages from server disk to new device (up to the last 100 chats, encrypted in indexeddb)

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