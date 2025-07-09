# Web app architecture

> This file about the app called "Web", which can be used by asking the digital team mates in a chat and later also via the OpenMates API. This file is NOT about the OpenMates web app, that allow users to access OpenMates via their web browser.

The web app allows for searching the web, reading and viewing websites & more.

## Skills

### Search

- clearly communicate search query & search provider
- default provider: Brave (official Brave Search API)
- include right click menu option for search request "Open in {search_provider}", which would open a new tab with the search query, to continue a manual search if wanted
- clearly show website results (title, favicon or preview image, link to open website results in new tab)
- don't forward brave search thumbnail urls or website thumbnails directly to use, but add /image-proxy endpoint to preview server, to hide users IP address and prevent third party tracking


### Read

- use Firecrawl to open and parse the text content of a website


### View

- use Firecrawl to create screenshots from a website, which will then be attached in llm message history, for processing by with vision capable LLM


## Focuses