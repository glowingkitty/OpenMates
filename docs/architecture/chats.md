# Chats architecture

## Folders

Chats can be managed in folders, including nested folders. Sorted by date, just as regular chats. Folders (like chats) have an auto selected icon from Lucide together with the color matching the request type, to allow for better quick identification.

## Right click / press & hold menu

> Feature not yet implemented

Show the chat summary and under that these options:

- mark as unread
- remind me (adds a template message to message input with "Remind me about this chat in a week.", which the user can send to trigger the reminder app)
- mark as completed (can be used by either user any time or also automatically in multi agent context)
- download (download yml of chat and all its messages)
- copy (copy yml of chat and all its messages to clipboard)
- delete (delete from indexeddb and also from server, including all files uploaded in the chat. does not delete usage entry, which is still needed for billing)

## Chats

- always have an Lucide icon by default (defined in pre-processing), not yet implemented
- a chat is marked as "Read" only once user has scrolled all the way to bottm of response