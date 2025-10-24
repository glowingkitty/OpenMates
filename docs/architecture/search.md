# Search architecture

## Auto complete

When user types in search input, show instant auto complete suggestions based on the tags of the chats (filtered to remove duplicates).

## Search

The search is searching with a low debounce time of 100ms after the user stops typing:

- all chat messages
- all chat titles
- all chat summaries
- all chat tags
- all settings menus & sub menus
- all apps in the app store (once apps are implemented)
- all app settings & memories of user (once apps are implemented)
- all app skills (once apps are implemented)
- all app focus modes (once apps are implemented)