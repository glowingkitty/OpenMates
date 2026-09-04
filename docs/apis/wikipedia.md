# Wikipedia API Notes

Last verified: 2026-08-28

OpenMates uses Wikimedia APIs to resolve explicitly requested Wikipedia titles and retrieve selected public article summaries. Browser, CLI, and SDK clients use the OpenMates proxy so Wikimedia receives the OpenMates server IP rather than the client IP.

## Provider

- Provider: Wikimedia Foundation
- Authentication: none for the public endpoints used by OpenMates
- Privacy policy: `https://foundation.wikimedia.org/wiki/Policy:Privacy_policy`
- OpenMates provider wrapper: `backend/shared/providers/wikimedia_provider.py`

## OpenMates Endpoints

- `GET /v1/wikipedia/search?query=<query>&language=<code>&limit=<1..10>` returns ordered public title metadata and marks disambiguation pages.
- `GET /v1/wikipedia/summary?title=<canonical-title>&language=<code>` returns selected public article metadata through the same bounded provider controls.

Both routes accept approved first-party session/device authentication and developer API keys. First-party requests are free. Developer API-key cache misses use the configured one-credit proxy policy. Per-user/IP limits, a shared outbound request budget, bounded concurrency, cache controls, and `Retry-After` handling protect Wikimedia and callers.

## Privacy And Encryption Boundary

- Generic `@` mention discovery never contacts Wikimedia.
- Only text typed after explicit `@wiki` activation, the requested language, and the selected canonical title leave OpenMates.
- The routes accept and return public article metadata only; they do not accept encrypted chat, memory, file, key, sync, or share material.
- Raw query text is not logged.
- Thumbnail bytes are fetched through the OpenMates image proxy.
- Selected summary prose is sanitized fail-closed before it becomes transient AI context.
- Canonical references stay inside client-encrypted message content; the backend does not add durable plaintext chat storage.

## Canonical References

Clients resolve human shorthand to `@wikipedia:<language>:<percent-encoded-title>`. A message may contain at most three references. The parser removes directives from ordinary prompt text, preserves their order, and adds only bounded sanitized source context before inference.

## Verified Behavior

- English `AlbertEin` search returns `Albert Einstein` first.
- `Mercury` results identify disambiguation pages, while an explicit canonical title resolves the intended article.
- Unsupported language, unavailable provider, local budget exhaustion, and blocked safety processing return visible errors without an unsafe fallback.
