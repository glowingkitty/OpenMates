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

## Prompt Injection Protection for External Data

**CRITICAL SECURITY REQUIREMENT**: All app skills that access external APIs or packages which gather external data (website content, video transcripts, emails, code from repositories, etc.) **must** assume that all returned data contains prompt injection attacks and must sanitize it before returning results.

### Mandatory Sanitization Process

**When It Applies**: Any skill that:
- Accesses external APIs (web scraping, REST APIs, third-party services)
- Retrieves content from external sources (websites, videos, documents, emails)
- Processes data from npm packages, pip packages, or CLI tools that fetch external content
- Returns any text or image content that originated from outside the OpenMates system

**Process**: Before returning data from an external source, app skills **must**:

1. **Split Long Text**: If text content exceeds 50,000 tokens, split it into chunks of 50,000 tokens maximum each
2. **Detect Prompt Injection Attacks**: Process each chunk through an optimized LLM function call with a specialized system prompt designed solely for prompt injection detection
3. **Sanitize Text Content**: If prompt injection is detected, sanitize the text content to remove or neutralize malicious instructions using the extracted `injection_strings`
4. **Combine Results**: Merge sanitized chunks back together, maintaining the original structure
5. **Reject Images**: If images contain prompt injection attacks (detected via image analysis), reject the image entirely
6. **Last Step Before Return**: This sanitization must be the **final step** before the app skill API endpoint returns data to the main processing system

### Implementation Details

- **Text Chunking**: Long text outputs must be split into blocks of **50,000 tokens maximum** before sanitization. Each chunk is processed separately, then results are combined.
- **Detection Method**: Uses an optimized LLM function call with system prompt and function definition from [`backend/apps/ai/prompt_injection_detection.yml`](../../../backend/apps/ai/prompt_injection_detection.yml)
- **System Prompt**: Specialized prompt that only detects and scores prompt injection attempts (score 0.0-10.0) - defined in the YAML file
- **Function Definition**: Tool definition for `detect_prompt_injection` that extracts exact injection strings for removal
- **Model Configuration**: Default model configured in [`backend/apps/ai/app.yml`](../../../backend/apps/ai/app.yml) under `skill_config.default_llms.content_sanitization_model`
- **Threshold**: Content with scores above 7.0 should be flagged or blocked; content between 5.0-7.0 should be reviewed
- **Sanitization**: Remove or neutralize detected injection patterns using extracted `injection_strings` from the detection result
- **Parallel Processing**: When processing multiple chunks, sanitize them in parallel when possible to improve performance

For detailed implementation guidelines, detection patterns, testing guidelines, and alternative prompt formats, see [Prompt Injection Protection](../prompt_injection_protection.md).

### Optional Override for Programmatic Access

**REST API / npm / pip / CLI Access**: For programmatic access to OpenMates (REST API, npm package, pip package, CLI), users can optionally disable prompt injection scanning at their own risk. However:

- **Default**: Scanning is **ON by default** for all programmatic access
- **Override**: Users must explicitly opt-out via configuration
- **Warning**: When disabled, users must acknowledge the security risk
- **Recommendation**: Only disable in trusted environments where external data sources are verified

### Why This Is Critical

External data sources (websites, videos, emails, etc.) can contain malicious instructions designed to manipulate the AI assistant. Without sanitization, these instructions could:

- Override system instructions
- Extract sensitive information
- Manipulate the assistant's behavior
- Bypass security controls

By sanitizing all external data before it reaches the main processing system, we ensure that prompt injection attacks are neutralized before they can affect the assistant's responses.
