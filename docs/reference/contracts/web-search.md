# Web Search

Search the public web for current information and return sanitized, attributable result groups consistently across all OpenMates platforms.


## Models

### WebSearchRequest

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `requests` | `array` | True | `{"max_items": 5, "min_items": 1}` |

### WebSearchRequestItem

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `id` | `string_or_integer` | False | `{"auto_generate_when_missing": "sequential_integer"}` |
| `query` | `string` | True | `{"blank": false, "max_length": 400, "min_length": 1, "trim": true}` |
| `count` | `integer` | False | `{"maximum": 20, "minimum": 1}` |
| `country` | `string` | False | `{"case_insensitive": true, "invalid_value": "fallback_to_US", "values": ["ALL", "AR", "AT", "AU", "BE", "BR", "CA", "CH", "CL", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "ID", "IN", "IT", "JP", "KR", "MX", "MY", "NL", false, "NZ", "PH", "PL", "PT", "RU", "SA", "SE", "TR", "TW", "US", "ZA"]}` |
| `search_lang` | `string` | False | `{"format": "iso_639_1"}` |
| `safesearch` | `enum` | False | `{"invalid_value": "fallback_to_moderate"}` |
| `filter_tabloids` | `boolean` | False | `{}` |

### WebSearchResult

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `title` | `string` | True | `{"blank": false, "html": "stripped"}` |
| `url` | `string` | True | `{"format": "absolute_http_or_https_url"}` |
| `description` | `string` | True | `{"html": "stripped"}` |
| `age` | `string` | False | `{}` |
| `meta_url` | `object` | False | `{}` |
| `language` | `string` | False | `{}` |
| `family_friendly` | `boolean` | False | `{}` |

### WebSearchResultGroup

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `id` | `string_or_integer` | True | `{}` |
| `results` | `array` | True | `{"max_items": 20, "min_items": 0}` |

### WebSearchResponse

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `results` | `array` | True | `{"max_items": 5, "min_items": 0, "unique_by": "id"}` |
| `provider` | `string` | True | `{}` |
| `suggestions_follow_up_requests` | `array` | False | `{}` |
| `error` | `string` | False | `{"raw_provider_diagnostics": "forbidden", "secrets": "forbidden"}` |

## Assertions
- `web-search.request.validated`: Invalid request shape, query, count, or batch size is rejected before provider execution.
- `web-search.request.ids-correlated`: Each result group preserves its caller ID or receives a unique sequential ID when none was supplied.
- `web-search.response.sanitized`: Provider titles and descriptions are sanitized as untrusted external data before client exposure or persistence.
- `web-search.results.bounded`: Each request returns no more than its requested count and never more than 20 results.
- `web-search.no-results.explicit`: A successful zero-hit request returns an empty finished result group and never an app-skill processing error.
- `web-search.provider-error.visible`: Provider failures produce a safe visible error and are never represented as a successful zero-hit search.
- `web-search.secrets.never-exposed`: Provider credentials, internal headers, raw diagnostics, and private logs never reach responses, embeds, clients, or committed examples.
- `web-search.surface-parity`: REST API, CLI, npm/pip SDKs, and web/Apple GUI preserve the same request, response, empty, error, privacy, and security semantics.

## Surfaces
- `rest_api`
- `cli`
- `sdks.npm`
- `sdks.pip`
- `gui.web`
- `gui.apple`

Bundle fingerprint: `738df115f3d77305ef48ca7e1865acecd0715462685c39e3e5a0ec2312552375`
