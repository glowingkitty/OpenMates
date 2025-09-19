# Apps architecture

![Apps header image](../../slides/openmates_pitch_slides/apps.jpg)

Apps are one of the core components of OpenMates. They allow your digital team mates to use various external providers to fullfill your requests - from searching the web, finding meetups, finding restaurants, generating images, transcribing videos, and much more.

![How apps work header image](../../slides/openmates_pitch_slides/how_apps_work.jpg)

## Skills

Skills are functions which are executed on the OpenMates server or via external providers, to fullfill your requests. From searching the web, finding meetups, finding restaurants, generating images, transcribing videos, and much more.

## Focus modes

Focus modes are temporary changes to the system prompt for a conversation to focus the chat on a specific goal, like planning a new software project, getting career advice and much more - all without you having to be an expert in AI prompt engineering.

## Providers

Providers are the external providers which are used to fullfill your requests. From searching the web, finding meetups, finding restaurants, generating images, transcribing videos, and much more.

## Settings & memories

Settings & memories are used to store your preferences and data, while minimizing the amount of data that is sent to the server and maximizing your privacy.


---

## Notes

> Some notes which are placed here for now.

### Skills implementation

- add support for multiple requests in same skill call. Example: videos | get transcript using list of YouTube urls, or web | search using list of search queries
- multiple requests in same skill call -> creates multiple celery tasks for same api endpoint
- Will be processed simultaneously, if api rate limit allows
- enforce third party api rate limits via dragonfly / cache based counter that auto expires after rate limit reset time (every second, every minute) and which counts up with every request, incl. auto retry once key expired (calculate when to retry task)
- always use celery for skills involving external APIs, regardless of processing time
- whenever an individual skill call is completed, response will be send via websocket connection to device which has chat currently open (for devices which don't have chat currently open, only completed assistant response that includes the app skill results will be sent once completed)
- use wait for direct response only for quick internal api endpoints which don’t relie on any external APIs or long processes

### Ignored

- save for example meetup groups or places which user doesn’t want to see anymore
- save hash of preview based on unique parameter like source url - for example meetup.com url or google places id
- save both a hash of the entry for fast check / lookup, but also content of preview encrypted via client stored encryption key, to also implement app specific "Ignored" list which also enables "Unignore" functionality

### Previews

- right click menu:
	- “Ignore” button -> hide preview and add under “Ignored” section at the end of slider / list of previews

#### Fullscreen mode

- shows preview with more details

#### Edit mode

- available for some previews in fullscreen mode (code, document, sheet, etc.)