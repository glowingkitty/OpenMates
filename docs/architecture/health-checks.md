# Health Checks Documentation

## Overview

OpenMates automatically monitors the health of all critical services:

- **LLM Providers** (Anthropic, Cerebras, Google, OpenAI, OpenRouter, Groq) + Brave Search
- **External Services** (Stripe, Sightengine, Brevo, AWS Bedrock, Vercel)
- **Internal App Services** (API servers and Celery workers)

Health checks run periodically via Celery Beat and can be queried via the `/health` and `/v1/health` API endpoints.

## Health Check Endpoints

### GET /health or /v1/health

Returns the overall health status of all services.

**Response Structure:**

- **Overall status**: `healthy`, `degraded`, or `unhealthy`
- **Providers**: Each provider includes status, last check timestamp, last error (if any), and response time history
- **Apps**: Each app includes overall status, API status, worker status, and last check timestamp

**Status Levels:**

- `healthy`: All checked services are operational
- `degraded`: Some services are unhealthy, but the system is partially operational
- `unhealthy`: Critical services are down or all services are failing

## Automatic Health Checks

### Provider Health Checks

**Task:** `health_check.check_all_providers`  
**Interval:** Every 1 minute (for providers with health endpoints) or 5 minutes (for test requests)  
**Execution:** Concurrent (all providers checked simultaneously)  
**Lock:** Distributed lock prevents multiple concurrent task executions

**Check Methods:**

1. **Health Endpoint Check** (1 minute)
   - For providers with dedicated `/health` endpoints
   - Simple HTTP GET request with 10 second timeout
   - Currently unused (all providers use test requests)

2. **Test Request Check** (5 minutes)
   - Makes minimal LLM completion request: "Answer short" → "1+2?"
   - Uses cheapest available model for the server
   - 15 second timeout per request
   - Model selection:
     - Anthropic: Prefers Haiku models (cost-effective)
     - Groq: Uses `llama-3.1-8b-instant` directly (fast, non-reasoning)
     - Others: Cheapest model by input cost per million tokens

**Monitored Providers:**

- Server IDs from provider registry: Anthropic, Cerebras, Google, OpenAI, OpenRouter, Groq
- Brave Search (connectivity check - verifies API key configuration and endpoint reachability via HEAD request, no billing)

**Retry Logic:**

- **Single attempt only** (no retry to avoid duplicate API calls)
- Healthy if attempt succeeds
- Unhealthy if attempt fails

**Response Time Tracking:**

- Stores last 5 response times with timestamps
- Cached for 10 minutes for trending analysis

### App Health Checks

**Task:** `health_check.check_all_apps`  
**Interval:** Every 5 minutes  
**Execution:** Concurrent (all apps checked simultaneously)  
**Lock:** Distributed lock prevents multiple concurrent task executions

**App Discovery:**

- Checks cache first for discovered apps metadata
- If cache empty, fetches metadata from each app's `/metadata` endpoint
- Filters by `SERVER_ENVIRONMENT` (only includes apps with valid stage components)
- Excludes apps in disabled list
- Falls back to filesystem scan if metadata unavailable

**Check Methods:**

1. **API Health Check**
   - HTTP GET to `http://app-{app_id}:8000/health`
   - Expects status 200 with `{"status": "ok"}`
   - 5 second timeout
   - **Retry Logic:** First attempt fails → Wait 1 second → Retry once

2. **Worker Health Check**
   - Celery worker inspection via `active_queues()`
   - Verifies worker listens to queue `app_{app_id}`
   - **Retry Logic:** First attempt fails → Wait 1 second → Retry once

**App Status:**

- `healthy`: Both API and worker responsive
- `degraded`: One component down, one up
- `unhealthy`: Both components down

### External Services Health Checks

**Task:** `health_check.check_external_services`
**Interval:** Every 5 minutes
**Execution:** Concurrent (all services checked simultaneously)

**Monitored Services:**

| Service           | Check Method                     | Vault Configuration                                              |
| ----------------- | -------------------------------- | ---------------------------------------------------------------- |
| **Stripe**        | `stripe.Account.retrieve()`      | `kv/data/providers/stripe:api_key`                               |
| **Sightengine**   | GET `/api/moderation/list`       | `kv/data/providers/sightengine:{api_user,api_secret}`            |
| **Brevo**         | GET `/v3/account`                | `kv/data/providers/brevo:api_key`                                |
| **AWS Bedrock**   | `boto3.list_foundation_models()` | `kv/data/providers/aws:{access_key_id,secret_access_key,region}` |
| **Vercel Domain** | HTTP GET (follow redirects)      | `VERCEL_DOMAIN` environment variable                             |

**Error Handling:**

- Missing credentials: `unhealthy` with `missing_credentials` error
- HTTP errors: Status code (e.g., `"500"`, `"403"`)
- Timeouts: `"timeout"` error
- Other errors: Sanitized before response

**Response Time Tracking:**

- Stores most recent response time with timestamp
- Cached for 10 minutes alongside other service statuses
- Measured in milliseconds

## Health Check Configuration

### Caching

Results are cached for 10 minutes (600 seconds) to prevent excessive API calls:

- Provider health: `health_check:provider:{provider_id}`
- App health: `health_check:app:{app_id}`

### Environment Variables

- `HEALTH_CHECK_TIMEOUT`: 15 seconds (test requests)
- `HEALTH_CHECK_ENDPOINT_TIMEOUT`: 10 seconds (health endpoints)
- `SERVER_ENVIRONMENT`: production, staging, or development

### Celery Beat Schedule

- Provider checks: Every 1 minute (health endpoints) or 5 minutes (test requests)
- App checks: Every 5 minutes
- External service checks: Every 5 minutes

## Error Handling & Sanitization

### Error Message Sanitization

Error messages are sanitized before returning via `/health` endpoint to protect sensitive information:

- HTTP status codes (4xx, 5xx) → Returns numeric code (e.g., "500", "404")
- Timeouts → Returns "timeout"
- Connection errors → Returns "connection_error"
- No available models → Returns "no_models"
- Unknown errors → Returns null (hidden from endpoint)

### Logging

- **INFO**: Service health status, check completion summaries, lock acquisition
- **WARNING**: First health check attempt fails (before retry for apps), lock already held by another instance
- **ERROR**: Health check failures, cache errors, lock acquisition failures
- **DEBUG**: Cache operations, detailed response times, model selection

Logs automatically filter sensitive data (API keys, email addresses, etc.).

## Health Check Workflow

1. **Celery Beat Scheduler** triggers periodic tasks
2. **Provider Checks** (every 1-5 minutes):
   - Get all server IDs from provider client registry
   - Check each LLM provider concurrently (parallel execution)
   - Try health endpoint or test request with cheapest model
   - Single attempt per provider (no retry)
   - Measure response time
   - Store result in cache (10 minute TTL)
   - Also check Brave Search separately
3. **App Checks** (every 5 minutes):
   - Discover enabled apps (cache → metadata endpoints → filesystem fallback)
   - Filter by server environment and disabled list
   - Check each app concurrently (parallel execution)
   - For each app:
     - Verify API health via HTTP GET (with retry)
     - Verify worker health via Celery inspection (with retry)
   - Store combined result in cache (10 minute TTL)
4. **External Service Checks** (every 5 minutes):
   - Check Stripe, Sightengine, Brevo, AWS Bedrock, Vercel concurrently
   - Fetch credentials from Vault (except Vercel domain from env var)
   - Perform lightweight API calls or HTTP requests
   - Measure response time
   - Store result in cache (10 minute TTL)
5. **When `/health` endpoint is called**:
   - Retrieve all cached health statuses (providers, apps, external services)
   - Calculate overall system status
   - Filter sensitive error messages
   - Return JSON response with all service statuses

## Monitoring & Alerting

### Logs to Monitor

- `Health check: Provider 'X' is unhealthy` - Provider is down
- `Health check: App 'X' is degraded` - App has partial functionality issues
- `Health check: Completed. Healthy: 15, Unhealthy: 1` - Summary of checks

### Recommended Alerts

Configure monitoring to alert on:

1. **Provider Unavailable** - Any LLM provider status = `unhealthy`
2. **App Degraded** - Any app status = `degraded`
3. **External Service Down** - Any external service status = `unhealthy`
   - Stripe payment processing unavailable
   - Email service (Brevo) unavailable
   - Content moderation (Sightengine) unavailable
   - LLM inference via AWS Bedrock unavailable
   - Frontend (Vercel domain) unavailable
4. **Multiple Services Down** - Overall system status = `unhealthy`
5. **Health Check Failures** - Celery task execution failures
6. **Cache Unavailable** - Health check results not being stored

## Planned Improvements

### Future External Service Checks

Consider adding health checks for:

- **Redis**: PING command, 1 minute interval (fast operation, currently implicit)
- **Directus**: `/system/health` endpoint, 5 minute interval (database/CMS)
- **Webhook Status**: Incoming webhook configuration validation

### Enhancement Roadmap

- Per-provider configuration for health endpoints
- Custom health check intervals per provider
- Webhook notifications on status changes
- Historical health metrics (1-week average response times)
- Per-region provider health checks (if multi-region)
- Health check metrics export (Prometheus format)
- Integration with APM tools

## Troubleshooting

### Provider Shows as Unhealthy

1. **Verify provider credentials** - Check Vault for API keys
2. **Check model availability** - Server may have no configured models that use it (check provider configs)
3. **Test provider directly** - Make a direct API call to verify connectivity
4. **Review health check logs** - Check Docker logs for detailed error messages
5. **Note**: Provider IDs in health checks are actually server IDs from the registry (e.g., "groq", "openrouter", not "openai")

### App Shows as Degraded

1. **Check API health** - Verify the app's `/health` endpoint responds
2. **Check worker status** - Verify Celery worker is listening to the app's queue
3. **Review app logs** - Check for errors in the app container

### Health Checks Not Running

1. **Verify Celery Beat** - Check logs for scheduled task execution
2. **Verify Celery workers** - Ensure workers are running and responsive
3. **Check cache connectivity** - Verify Redis is accessible (required for locks and storage)
4. **Check distributed locks** - If another instance is running checks, logs will show "lock already held"
5. **Verify app discovery** - Ensure apps are discoverable via metadata endpoints or filesystem

## Related Documentation

- [Architecture Overview](./README.md)
- [Skill Architecture](./app-skills.md)
- [App Structure](./apps/README.md)
- [Security](./security.md)
