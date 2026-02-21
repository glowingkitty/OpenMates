# Apps

Apps are one of the core components of OpenMates. They allow your digital team mates to use various external providers to fulfill your requests - from searching the web, finding meetups, finding restaurants, generating images, transcribing videos, and much more.

> **Note**: Mates can also list apps as previews with links to the app store entry

## How Apps Work

- [Skills](skills.md) - Functions executed on the server or via external providers
- [Focus Modes](focus-modes.md) - Temporary system prompt changes for specialized assistance
- [App Store](app-store.md) - Browse and discover apps, skills, and pricing
- [Settings & Memories](settings-and-memories.md) - Per-app preferences and data storage

**Key Features:**

- Support for multiple requests per skill call (up to 5 parallel requests)
- Automatic parallel processing via Celery tasks
- Rate limiting and retry logic for external APIs

## Individual Apps

### Productivity

- [Code](code.md) - View, write, and edit code with embedded previews
- [Docs](docs.md) - Document viewing and embedded previews
- [PDF](pdf.md) - PDF viewing, search, and analysis
- [Sheets](sheets.md) - Spreadsheet viewing and editing
- [Slides](slides.md) - Presentation creation with RevealJS
- [Mail](mail.md) - Compose, send, and manage emails
- [Reminder](reminder.md) - Schedule reminders for chats

### Research & Learning

- [Web](web.md) - Web search, website reading, and embedded previews
- [News](news.md) - News search via Brave Search API
- [Books](books.md) - Search within ebooks (EPUB, MOBI)
- [Study](study.md) - Learning focus modes and educational paths
- [Math](math.md) - LaTeX math rendering

### Media & Creative

- [Images](images.md) - AI image generation with embed storage
- [Videos](videos.md) - Video previews, YouTube transcript extraction
- [Music](music.md) - Audio-to-sheet-music, multi-provider search
- [Drawing](drawing.md) - Creative canvas with AI feedback (planned)
- [Design](design.md) - Figma/Penpot integration (planned)

### Lifestyle

- [Travel](travel.md) - Trip planning with settings and memories
- [Shopping](shopping.md) - Buy lists and purchase decision tracking
- [Fitness](fitness.md) - Fitness class search and tracking
- [Health](health.md) - Medication database and appointment tracking
- [Plants](plants.md) - Plant collection management (planned)
- [Contacts](contacts.md) - Contact management and public figure search
- [Events](events.md) - Location-based event search (planned)
- [Home](home.md) - Smart home management (planned)

### Professional

- [Jobs](jobs.md) - Career insights and job search
- [Business](business.md) - Startup ecosystem data via F6S
- [Coaching](coaching.md) - Coaching focus modes including ADD coach
- [Maps](maps.md) - Place search and location details

## For Developers

- [Function Calling](function-calling.md) - How LLM function calling integrates with apps
- [Focus Modes Implementation](focus-modes-implementation.md) - Technical implementation details
- [Action Confirmation](action-confirmation.md) - Security for write/sensitive operations
- [App Skills Architecture](../architecture/app-skills.md) - Technical architecture details
- [REST API](../architecture/rest-api.md) - Developer API for skills and focus modes

## Implementation Notes

- **Multiple requests**: All skills support up to 5 parallel requests per skill call
- **Parallel processing**: Multiple requests create multiple Celery tasks processed simultaneously
- **Rate limiting**: Enforced via Dragonfly/cache-based counters with auto-retry
- **Celery usage**: All external API skills use Celery regardless of processing time
- **Response delivery**: Results sent via WebSocket as each skill call completes
