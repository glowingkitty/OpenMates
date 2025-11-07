# Share chat architecture

> not yet implemented. This is the planned architecture of a still to be implemented feature.

- options: “Share with user” and “Share with public”
- “Share with user” requires entering user email address
	- sends email with “chat was shared with you” and link /chat/{chatid}#key={encryption-key}
	- adds hash of email address to list of users who is allowed to view chat
	- once chat is opened in web app, server checks if email hash is on list of allowed users. If yes, hash of email is replaced with hash of user id (SHA256(user_id)) so same user can access even after email change. User ID never changes, so access persists.
	- client receives the encrypted chat, uses the #{key} to decrypt the chat, then saves the key encrypted via client master encryption key under user settings “shared_chats_keys”
	- url is updated and key removed
	- on following reloads, the stored key is used for the chat and the #{key} url is no longer needed
- “Share with public”: similar principle and flow, just without the check if the user is allowed to access the chat and instead we only check for “shared_public” true or false
- should reliably prevent also indexing via search engines and also prevent the server from seeing the key in the url request
- user interface needs to show which messages are not yet synced with public version and allow to sync / update public chat