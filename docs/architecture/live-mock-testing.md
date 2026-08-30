# Cost-Safe AI Test Replay

Daily AI coverage has two explicit modes governed by
`architecture.daily-ai-test-inference@1`.

## Scheduled Replay

`TEST_LIVE_MOCK` runs local AI orchestration and replays wrapped LLM and HTTP
provider responses. Cache misses fail before provider dispatch. Legacy
`TEST_MOCK` fixtures replay cached preprocessing, response, and postprocessing
events; the worker must not run the live postprocessor afterward.

`scripts/daily_ai_test_manifest.json` is the scheduled-test policy source.
Unmarked chat-driving specs, expensive real-inference specs, and specs with
missing cache groups are excluded until they are explicitly repaired or their
cassettes are manually promoted. Run:

```bash
python3 scripts/audit_daily_ai_test_inference.py
```

## Bounded Real Canaries

One fixed and one rotating spec use `TEST_LIVE_REAL`. Both derive the same UTC
daily group and reserve conservative provider cost in Dragonfly before wrapped
LLM or HTTP dispatch. The default shared cap is EUR 0.25 and the default
LLM reservation is derived from provider pricing with a conservative UTF-8 input
token upper bound and bounded max output. Budget storage failure, exhaustion,
invalid pricing, and variable-price HTTP providers fail before dispatch and
never fall back to another provider.

These controls are ignored in production. Requests without explicit test
context retain ordinary inference behavior.

## Manual Recording

`TEST_LIVE_RECORD` never reads committed cassettes. It records into a
request-scoped candidate directory under
`/tmp/openmates-live-mock-candidates/<task-id>` by default. Save failures are
fatal. Validate and promote named groups only after the real test passes:

```bash
python3 scripts/import_live_mock_cache.py <candidate-root> --group <group> \
  --passed-real-run --passed-zero-call-replay
```

Promotion validates every JSON file before replacing canonical groups and keeps
rollback backups during the transaction. Rerun the scenario in replay mode
after promotion; a promoted cache is not accepted until that replay passes.

## Privacy Boundary

Reports may include mode, phase, provider, model, cache status, calls, tokens,
reserved cost, and normalized failures. They must not include prompts,
responses, tool payloads, cache keys, user/chat identifiers, credentials, or raw
provider errors.
