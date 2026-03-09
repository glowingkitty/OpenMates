# API Integration Rules

Mandatory workflow for integrating new external APIs. For test script templates and documentation format, run:
`python3 scripts/sessions.py context --doc add-api-ref`

---

## Rule 1: Research Before Building

If the user hasn't provided API details, find and evaluate the official API:
- Does it cover requirements? Map each requirement to a specific endpoint.
- Authentication type? Rate limits? Pricing?
- Free tier limits? Developer signup difficulty?

Present findings and get user confirmation before proceeding.

## Rule 2: Build a Standalone Test Script

Location: `scripts/api_tests/test_<provider>_api.py`

Requirements:
- Load secrets via vault by default
- Accept `--api-key` for manual override
- Accept `--test` for running specific tests, `--list` to list them
- Use `argparse` for CLI parsing
- Print structured output with timing
- Handle errors gracefully

## Rule 3: Test Thoroughly

Minimum test cases:
- Happy path with valid input
- Edge cases (empty, long, special chars, unicode)
- Boundary conditions (max items, min params)
- Error handling (invalid key, malformed request, nonexistent resource)
- Rate limit behavior (if applicable)

## Rule 4: Document the Integration

Create summary at `docs/apis/<provider_name>.md` with:
- Overview, authentication, endpoints used
- Input/output structure with tables
- Pricing (free tier, paid tier, estimated cost)
- Limitations (rate limits, freshness, coverage gaps)
- Scaling considerations

## Rule 5: Firecrawl Fallback

If no official API exists or it's inaccessible:
1. Inform user why and get confirmation before reverse-engineering
2. Use `firecrawl_map` + `firecrawl_scrape` with JSON schema
3. Follow same test script standards
4. Add fragility warnings and maintenance notes to docs
