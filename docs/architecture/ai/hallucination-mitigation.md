---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/processing/url_validator.py
  - backend/apps/ai/tasks/stream_consumer.py
  - backend/apps/ai/base_instructions.yml
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/main_processor.py
  - backend/apps/ai/tasks/ask_skill_task.py
---

# Hallucination Mitigation

> Multi-layered defenses against fabricated URLs, tool-result hallucinations, and unsupported claims in AI responses.

## Why This Exists

LLMs fabricate URLs, invent tool results, and make unsupported claims. OpenMates addresses this through instruction design, automatic URL validation, tool preselection, and resilient tool-call handling.

## How It Works

### 1. Instruction-Based Guardrails

[`base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) contains two key instruction layers:

- **`base_ethics_instruction`**: Ethics layer discouraging fabrication
- **`base_url_sourcing_instruction`**: Explicit rules requiring URLs to come from conversation context, tool results, or well-known canonical sources. The model is instructed to prefer offering a web search over guessing links.

### 2. Automatic URL Validation and Replacement

[`url_validator.py`](../../backend/apps/ai/processing/url_validator.py) validates markdown links during streaming and replaces broken ones with Brave search URLs.

**Process:**
- Extracts markdown links (`[text](url)`) from streamed paragraphs
- Validates each URL via `HEAD` request (fallback to `GET`) through Webshare rotating residential proxy
- Uses random User-Agent generation and randomized HTTP headers to avoid bot detection
- Skips localhost patterns and fragment-only URLs

**Broken link handling:**
- **4xx responses** (401, 403, 404): Treated as broken, collected for replacement
- **5xx/timeouts**: Treated as temporary server issues, left as-is
- After streaming completes, broken URLs are replaced with Brave search links: `[Python docs](https://search.brave.com/search?q=Python%20docs)`

[`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py) publishes URL correction events to the frontend after validation completes.

### 3. Tool Preselection

The preprocessor ([`preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)) narrows available tools to only what is relevant for the request. This reduces the chance of the model selecting irrelevant tools or fabricating tool usage for tools it should not have access to.

### 4. Tool-Name Hallucination Resilience

The main processor ([`main_processor.py`](../../backend/apps/ai/processing/main_processor.py)) builds a resolver map for tool-name variants (hyphen vs underscore, case differences). Minor hallucinations in tool identifiers are automatically corrected instead of failing.

### 5. Tool Availability Guarantees

[`ask_skill_task.py`](../../backend/apps/ai/tasks/ask_skill_task.py) treats missing tool metadata as a critical reliability issue. It includes a cache-miss fallback to ensure tool definitions are actually available to the model, reducing the chance the model "pretends" to have searched or read content.

## Edge Cases

- Plain-text URLs (not in markdown link syntax) are not validated -- only `[text](url)` patterns are checked.
- Brave search replacement preserves the link text but redirects to search results; the user must still verify the result.
- Temporary server issues (5xx) are intentionally not treated as broken to avoid overcorrecting valid links.

## Planned Improvements

- **Docs search before code generation**: Enforce a "search current docs first" step before generating code for framework/library APIs.
- **Post-generation lint/typecheck**: Run linters in sandboxed environments (e2b) on generated code, with automatic fix loops for critical errors.
- **Stronger research focus modes**: Multi-step research/verification behaviors (plan, search, read, synthesize).

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- pipeline context
- [Prompt Injection Protection](../privacy/prompt-injection.md) -- protecting against malicious content in tool results
