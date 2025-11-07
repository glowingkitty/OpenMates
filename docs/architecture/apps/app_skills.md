# App Skills

Skills are functions that your digital team mates can use to fulfill your requests. They can search the web, find restaurants, generate images, transcribe videos, and much more.

## Multiple Requests Per Skill Call

All skills support processing multiple requests in a single skill call. This enables parallel processing of related tasks, improving efficiency and user experience.

### How It Works

When you make a request that involves multiple items (e.g., searching for multiple topics, getting transcripts from multiple videos), the system:

1. **Processes in Parallel**: All requests are processed simultaneously (up to 9 parallel requests)
2. **Incremental Results**: Results appear incrementally as each sub-request completes
3. **Completion**: The overall request is considered complete once all sub-requests are finished

**Example:** If you ask to search for 9 different topics, the system will process all 9 searches in parallel. You'll see results appear one by one as each search completes, rather than waiting for all 9 to finish.

### Example Use Cases

**Web Search:**

- Search for multiple topics at once: "Search for Python async programming, FastAPI best practices, and Celery task queues"
- All searches run in parallel and results appear as they complete

**Video Transcripts:**

- Get transcripts from multiple YouTube videos in one request
- Each transcript is processed independently and results appear incrementally

### Reliable Processing

The system ensures your requests are processed reliably:

- **No Rejections**: Requests are never rejected due to rate limits. Instead, they're queued and processed when limits allow
- **Automatic Retry**: If a request hits a rate limit, it automatically retries once the limit resets
- **Parallel Processing**: Multiple requests are processed simultaneously when possible (up to 9 parallel requests)
- **Incremental Results**: You see results as they complete, rather than waiting for everything to finish

### Long-Running Tasks and Auto-Followup Messages

When you make a request that takes longer to process (e.g., generating images, processing multiple videos, or when many parallel searches are queued due to rate limits):

**Via Chatbot (Web Interface):**

- The chatbot **continues responding by default** and does not wait for task completion
- Once the task completes, the system automatically sends a followup message in the chat
- Example: "I am done with generating the images. Here you go: [results]"
- This ensures the conversation flow remains natural and responsive, and you can make followup requests while waiting

**Result Display:**

- Results appear incrementally as each sub-request completes
- You see partial results immediately rather than waiting for everything to finish
- Example: With 9 parallel searches, results appear one by one as each search completes
- A request is considered complete once all its sub-requests are finished

## Skill Results

Skills return results in a structured format that your digital team mates can use to provide you with helpful information.

### Previews

Skills return previews - visual representations of the results. For example:

- **Web Search**: Search result cards with titles, snippets, and links
- **Code Files**: Code snippets with syntax highlighting
- **Locations**: Map previews with addresses and details
- **Videos**: Video thumbnails with metadata

### Follow-up Suggestions

Skills can suggest follow-up actions based on the results. For example:

- After a web search: "Search more in depth", "Create a PDF report"
- After finding restaurants: "Get directions", "Check reviews"

### Additional Instructions

Some skills provide additional context or instructions to help your digital team mate better understand and present the results to you.
