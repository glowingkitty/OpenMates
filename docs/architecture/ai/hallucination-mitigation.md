---
status: active
last_verified: 2026-05-10
key_files:
  - backend/apps/ai/processing/url_validator.py
  - backend/apps/ai/tasks/stream_consumer.py
  - backend/apps/ai/base_instructions.yml
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/main_processor.py
  - backend/apps/ai/tasks/ask_skill_task.py
  - backend/shared/python_utils/url_normalizer.py
  - backend/shared/providers/groq/safeguard.py
---

# Hallucination Mitigation

> Multi-layered defenses against fabricated URLs, tool-result hallucinations, and unsupported claims in AI responses.

## Why This Exists

LLMs fabricate URLs, invent tool results, and make unsupported claims. OpenMates addresses this through instruction design, source-based URL allowlisting, automatic URL validation, tool preselection, and resilient tool-call handling.

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

### 3. Assistant URL Source Allowlist and Safeguard

Final assistant responses are scanned for plain and Markdown HTTP(S) URLs before persistence. This catches URLs that the model fabricated or generated from malicious source instructions, including URLs that encode sensitive user data in the path, query string, fragment, or obfuscated payload.

**Source allowlist gate:** [`url_normalizer.py`](../../backend/shared/python_utils/url_normalizer.py) extracts exact URL tokens recursively from source content available before the final answer:

- user messages and relevant chat history
- tool call inputs/results
- app skill and embed payloads, including web/search/code/document/email/transcript data

Every assistant URL must match one source URL byte-for-byte. If not, it is removed immediately. The model is not allowed to create a new URL by combining source fragments, decoding instructions, or encoding secrets.

**Batched safeguard gate:** URLs that pass the exact-source gate are sent as a JSON list to `openai/gpt-oss-safeguard-20b` via Groq function/tool calling. The required tool is `report_malicious_urls`, which returns:

- `all_urls_safe`: true only when no supplied URL is unsafe
- `malicious_urls`: exact URLs to remove, each with a category and reason

The safeguard prompt is optimized for malicious URL detection. It reports URLs containing or suggesting secrets, auth/session tokens, personal data, encoded private data, prompt-injection payloads, ciphertext-like exfiltration, tracking identifiers, phishing/malware, or credential-exfiltration patterns.

**Fail-closed behavior:** if the safeguard call fails, returns malformed arguments, references an unknown URL, or rewrites a URL, all URLs in that batch are removed. The returned model data is never used as a replacement URL; it only identifies which exact supplied URLs to remove.

### 4. Tool Preselection

The preprocessor ([`preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)) narrows available tools to only what is relevant for the request. This reduces the chance of the model selecting irrelevant tools or fabricating tool usage for tools it should not have access to.

### 5. Tool-Name Hallucination Resilience

The main processor ([`main_processor.py`](../../backend/apps/ai/processing/main_processor.py)) builds a resolver map for tool-name variants (hyphen vs underscore, case differences). Minor hallucinations in tool identifiers are automatically corrected instead of failing.

### 6. Tool Availability Guarantees

[`ask_skill_task.py`](../../backend/apps/ai/tasks/ask_skill_task.py) treats missing tool metadata as a critical reliability issue. It includes a cache-miss fallback to ensure tool definitions are actually available to the model, reducing the chance the model "pretends" to have searched or read content.

## Edge Cases

- Broken-link validation only checks Markdown links during streaming, but final URL source/safeguard processing checks both plain-text URLs and Markdown links.
- Brave search replacement preserves the link text but redirects to search results; the user must still verify the result.
- Temporary server issues (5xx) are intentionally not treated as broken to avoid overcorrecting valid links.
- Source allowlisting requires exact URL matches. If a tool result exposes one canonical URL and the assistant formats a different tracking-free variant, the variant is removed unless it also appeared in source content.

## Planned Improvements

- **Docs search before code generation**: Enforce a "search current docs first" step before generating code for framework/library APIs.
- **Post-generation lint/typecheck**: Run linters in sandboxed environments (e2b) on generated code, with automatic fix loops for critical errors.
- **Stronger research focus modes**: Multi-step research/verification behaviors (plan, search, read, synthesize).

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- pipeline context
- [Prompt Injection Protection](../privacy/prompt-injection.md) -- protecting against malicious content in tool results
