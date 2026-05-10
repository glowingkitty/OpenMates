---
status: active
last_verified: 2026-05-10
key_files:
  - backend/core/api/app/utils/text_sanitization.py
  - backend/apps/ai/processing/content_sanitization.py
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/tasks/stream_consumer.py
  - backend/apps/ai/prompt_injection_detection.yml
  - backend/shared/python_utils/url_normalizer.py
  - backend/shared/providers/groq/safeguard.py
  - backend/preview/app/services/content_sanitization.py
  - backend/preview/app/services/text_sanitization.py
  - backend/apps/ai/app.yml
  - backend/preview/app/config.py
---

# Prompt Injection Protection

> Defense-in-depth against prompt injection attacks using character-level ASCII smuggling protection and LLM-based semantic detection across all entry points.

## Why This Exists

External content processed by app skills (websites, emails, code, PDFs, video transcripts) may contain malicious instructions targeting the LLM. Attack vectors include direct instructions in text, hidden Unicode characters (ASCII smuggling), metadata injection via Open Graph tags, and obfuscated instructions in code comments.

## How It Works

### Layer 0: ASCII Smuggling Protection (Character-Level)

[`text_sanitization.py`](../../backend/core/api/app/utils/text_sanitization.py) strips invisible Unicode characters that encode hidden instructions:

| Category | Unicode Range | Danger |
|----------|---------------|--------|
| Unicode Tags | U+E0000-U+E007F | Critical -- encodes hidden ASCII text |
| Variant Selectors | U+FE00-U+FE0F, U+E0100-U+E01EF | High -- hidden data encoding |
| Zero-Width Characters | U+200B, U+200C, U+200D, U+2060, U+FEFF | High -- binary data patterns |
| BiDi Controls | U+200E-U+200F, U+202A-U+202E, U+2066-U+2069 | Medium -- text reordering |
| ASCII Control | 0x00-0x1F, 0x7F (except tab/newline/return) | Low |

**Entry points protected:**
1. WebSocket handler -- all user messages from web app
2. REST API endpoints -- all programmatic requests
3. AI preprocessor -- final safety check before LLM

**Process:** Detect and decode hidden ASCII content (logged as security alert), remove all invisible characters, normalize Unicode to NFC form.

### Layer 1: LLM-Based Prompt Injection Detection (Semantic-Level)

[`content_sanitization.py`](../../backend/apps/ai/processing/content_sanitization.py) runs a specialized LLM to detect malicious instructions in visible text from app skill results.

**Model configuration:**
- **Main backend**: `openai/gpt-oss-safeguard-20b` via Groq (primary) with OpenRouter fallback. Configured in [`app.yml`](../../backend/apps/ai/app.yml) as `content_sanitization_model`.
- **Preview server**: `llama-3.3-70b-versatile` via Groq. Configured in [`config.py`](../../backend/preview/app/config.py).

**Detection system prompt and thresholds** are defined in [`prompt_injection_detection.yml`](../../backend/apps/ai/prompt_injection_detection.yml).

**Scoring and actions:**

| Score | Action |
|-------|--------|
| >= 7.0 (block threshold) | Block entire content (return empty string) |
| 5.0-6.9 (review threshold) | Replace detected injection strings with `[PROMPT INJECTION DETECTED & REMOVED]` |
| < 5.0 with detected strings | Replace detected strings with placeholder |
| < 5.0, no strings | Pass through |

**Text chunking**: Long text outputs are split into 50,000-token chunks, processed separately, then combined. [`content_sanitization.py`](../../backend/apps/ai/processing/content_sanitization.py) implements word-boundary-aware splitting via `_split_text_into_chunks()`.

**Execution order**: ASCII smuggling runs FIRST on external content, then LLM detection runs as the LAST step before app skill endpoints return data to main processing.

### Preview Server Sanitization

The preview server ([`backend/preview/`](../../backend/preview/)) applies both layers to metadata fetched from external websites and YouTube videos.

| Source | Fields Sanitized |
|--------|-----------------|
| Website | title, description, site_name |
| YouTube Video | title, description, channel_name |
| YouTube Channel | title, description |

Preview metadata text is sanitized before the LLM sees it. Raw URLs, thumbnails, and favicons are not rewritten by the preview server; assistant-visible links are handled by the response URL safety layer below.

**Graceful degradation**: If Groq API is unavailable, ASCII smuggling protection still runs. LLM detection is skipped with a warning log.

### Layer 2: Assistant URL Source and Safety Checks

Assistant responses can turn prompt-injected source text into malicious links, for example by encoding chat secrets in a URL path or query string. OpenMates therefore treats assistant-visible URLs as generated content that must be proven safe before the final response is persisted or streamed as the corrected final text.

[`url_normalizer.py`](../../backend/shared/python_utils/url_normalizer.py) and [`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py) enforce two gates:

1. **Exact source allowlist** -- every URL in the assistant response must already exist byte-for-byte in trusted source material available before generation.
2. **Batched safeguard classification** -- URLs that pass the source allowlist are sent in one batch to `openai/gpt-oss-safeguard-20b` using function/tool calling. The model reports only malicious URLs via `report_malicious_urls`.

**Source material for the allowlist:**

- User-typed message content and relevant chat history
- Tool results and app skill outputs passed back to main processing
- Embed preview/result payloads such as web pages, web search results, code results, documents, emails, and transcripts

**Removal rules:**

- If an assistant URL is not present exactly in the source allowlist, remove it immediately without an LLM call.
- If the safeguard reports a source-backed URL as malicious, remove it.
- If the safeguard call fails, returns malformed tool arguments, references unknown URLs, or rewrites URLs, fail closed for the affected batch and remove those URLs.

**Why this is not URL parameter stripping:** parameters, fragments, and paths are preserved when they are legitimate source URLs. The safety question is whether the exact URL came from source content and whether the full URL contains secrets, personal data, encoded payloads, prompt-injection instructions, phishing/malware indicators, or credential-exfiltration patterns.

### Additional Defenses

- **Manual confirmation for sensitive skills**: Certain app skills require user confirmation before execution.
- **Assistant URL source allowlist**: Generated responses may only keep URLs that came from user/tool/embed source content exactly, then pass batched safeguard classification.
- **CLI terminal command blocking**: The CLI prevents LLM from executing arbitrary shell commands, providing safe file-reading instead.

### Programmatic API Override

For REST API, npm package, pip package, and CLI access, users can optionally disable prompt injection scanning at their own risk. Scanning is ON by default. The web interface always enforces protection.

## Edge Cases

- **Groq API outage**: Content is returned with character-level sanitization only (ASCII smuggling protection has no external dependency).
- **False positives**: Content discussing AI systems or prompt engineering may trigger moderate scores (5.0-6.9). The review threshold allows these through with targeted string replacement rather than full blocking.
- **Cached preview metadata**: Sanitization happens at fetch time. Cached metadata is already sanitized.

## Related Docs

- [Hallucination Mitigation](../ai/hallucination-mitigation.md) -- related but distinct defense layer
- [PII Protection](./pii-protection.md) -- client-side PII detection
