# LLM Hallucination Mitigation

This document summarizes the **implemented** and **planned** measures OpenMates uses to reduce LLM hallucinations (incorrect or fabricated content), with an emphasis on link/source hallucinations and tool-result hallucinations.

## Goals

- Reduce **fabricated URLs**, broken links, and incorrect citations.
- Reduce **tool-result hallucinations** (model “pretending” to have executed a tool).
- Encourage “ask / search / verify” behavior when the model lacks evidence.

## Current (Implemented)

### 1) Prompting / instruction design (ethics + accuracy constraints)

Base instructions include an ethics layer and explicit rules that discourage fabrication, especially for URLs:

- **Base ethics instruction**: `backend/apps/ai/base_instructions.yml` (`base_ethics_instruction`)
- **URL sourcing rules (anti-URL-hallucination)**: `backend/apps/ai/base_instructions.yml` (`base_url_sourcing_instruction`)
  - Only use URLs from conversation/tool results or well-known canonical sources
  - Prefer offering web-search over guessing links

Related system-prompt composition is documented in `docs/architecture/message_processing.md`.

### 2) Automatic URL validation + Brave search replacement (404 / 4xx)

OpenMates validates markdown links during streaming and replaces broken links with Brave search URLs:

- URL extraction/validation: `backend/apps/ai/processing/url_validator.py`
- Streaming integration + correction publish: `backend/apps/ai/tasks/stream_consumer.py`

**Anti-detection features** (to avoid datacenter IP blocking):
- Webshare rotating residential proxy for URL validation requests
- Random User-Agent generation (via `user-agents` library)
- Randomized HTTP headers (Accept-Language, DNT, etc.)

**Behavior summary:**
- Only **markdown links** like `[text](https://...)` are extracted/validated.
- URLs are checked via `HEAD` (fallback to `GET`) with redirects enabled, routed through Webshare proxy.
- **4xx** links (401, 403, 404, etc.) are treated as broken and collected; **5xx/timeouts** are treated as temporary (not auto-removed).
- After streaming completes, broken URLs are replaced with Brave search links using the original link text.
  - Example: `[Python docs](https://broken-link.com)` → `[Python docs](https://search.brave.com/search?q=Python%20docs)`
- This approach is simple, reliable (can't fail), zero-cost (no LLM call), and preserves the user's ability to find the intended content.

### 3) Tool preselection (reduce irrelevant tools → fewer “wrong tool” paths)

Before main inference, preprocessing narrows the available tools/focus modes to only what’s relevant for the user request. This reduces chances of the model selecting irrelevant tools or fabricating tool usage:

- Preprocessing: `backend/apps/ai/processing/preprocessor.py`
- Architecture overview: `docs/architecture/message_processing.md`

### 4) Resilience to common tool-call “name hallucinations”

The main processor builds a resolver map for tool-name variants (e.g., hyphen vs underscore) so minor hallucinations in tool identifiers don’t derail execution:

- Tool resolver map: `backend/apps/ai/processing/main_processor.py`

### 5) Prevent “no tools available” → tool-result hallucinations

The system treats missing tool metadata as a critical reliability issue and includes a cache fallback to ensure tools are actually available to the model. This reduces the chance the model “pretends” to have searched/read:

- Metadata loading + fallback + warnings: `backend/apps/ai/tasks/ask_skill_task.py`

## Planned / In Progress

### 1) “Docs search required” for code generation

For code-writing flows, enforce a “search current docs first” step (via skills / internal docs search) before generating final code, especially for framework/library APIs that change quickly.

### 2) Post-generation lint/typecheck loop for code

After code generation completes:
- Run linters/typecheck on produced files (likely via an isolated runner like e2b)
- If errors are found, trigger a follow-up inference pass to fix the reported issues

### 3) Stronger research strategies via focus modes

Expand and harden focus modes that guide the model into multi-step research/verification behaviors (e.g., plan → search → read → synthesize), reducing unsupported claims.

## Known Gaps / Limitations

- URL validation currently targets markdown links; plain-text URLs may not be validated.
- This mitigates *broken* URLs and URL fabrication patterns, but does not fully verify factual claims without explicit retrieval/verification steps.
- Temporary network/server issues (timeouts/5xx) are intentionally treated as non-broken to avoid overcorrecting valid links.
- Brave search replacement preserves the link but redirects to search results; the user must still verify they found the correct resource.
