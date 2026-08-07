---
status: active
doc_type: explanation
audience:
  - contributors
last_verified: 2026-08-07
contracts:
  - feature.app-skill.web-search@1
related_domains:
  - app-skills
  - embeds
  - provider-routing
claims:
  - id: semantic-web-search-contract-boundary
    type: static
    file: scripts/tests/test_contract_docs.py
    assertion: semantic-web-search-contract-boundary
---

# Web Search

Web Search discovers public pages and normalizes provider-specific data into the
stable models defined by `feature.app-skill.web-search`. This page explains why
the architecture has its current boundaries; it does not repeat contract field
constraints or implementation evidence.

## Flow

```text
REST / CLI / SDKs / GUI
          |
          v
   Web Search skill
          |
          v
   Provider adapter
          |
          v
 Sanitize and normalize
          |
          v
 Shared grouped response
          |
          v
 Platform presentation
```

## Boundaries

Web Search owns request validation, provider execution, result sanitization,
grouping, and provider-independent empty/error semantics. Web Read owns full
extraction of a known URL. Clients own presentation but must preserve the same
contract meanings.

## Decisions

Provider results are normalized before reaching clients so the provider or
internal implementation can be replaced without redefining the feature.

A successful zero-hit search and a provider failure remain different outcomes.
External titles, descriptions, metadata, and URLs are always untrusted data.

SDKs means npm and pip parity. GUI means web and Apple semantic parity. Missing
subsurface behavior remains a coverage gap unless an approved contract exception
documents a platform-owned difference and equivalent outcome.

## Change Impact

Provider internals can change without amending the feature contract when all
assertions remain true. Model, constraint, example, error, security, privacy,
surface, or approved-exception changes require a new approved contract version.
