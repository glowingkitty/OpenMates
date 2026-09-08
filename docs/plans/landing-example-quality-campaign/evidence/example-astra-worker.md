# TASK-3176 / TASK-10: Astra habit tracker

- Session: `8999`; distinct worktree: `.openmates-agent-worktrees/agent-8999`.
- Actual Codex thread: `01a080f6-ab97-7f51-97c8-45e5ed94aada`; coordinator Plan already records this thread.
- Tasks activity and connection commands returned HTTP 429. Coordinator instructed all workers to stop Tasks API calls for at least ten minutes and defer posting to serialized recovery. No attribution success claimed.
- Live CLI mentions list confirms `@GPT-6-Astra` exists.
- Existing `habit-garden-web-application.ts` identifies Gemini 3.1 Pro, source chat `c9a2db86-527b-4139-a407-be6865681bc0`, and empty follow-up suggestions. It is not an Astra candidate. No existing example changed.
- Approved opening submitted verbatim using the designated source CLI, `chats new`, slug `task-3176-astra-habit-tracker`. Initial settings request encountered HTTP 429 and the CLI entered its built-in 61-second backoff. Source chat ID not yet returned.
- No account memory changes, audio generation, shared renderer edits, or runtime changes.
- Pending: complete source response, actual model routing, content review, generated app interactions, phone/laptop rendering, persistence, publication/proof and eventual speech-pilot gate.

Local milestone record for later acknowledged task posting; this is not a passing admission record.

## Real CLI failure

- Source chat: `2e699097-cfdd-42bb-8cad-3e2337d15bc1`.
- Returned message ID: `2c0be500-72b2-508d-9889-4901ca73156c`.
- CLI returned status `completed`, model `GPT-6 Astra`, mate `Sophia`, category `software_development`, but assistant body was exactly `chat.an_error_occured`.
- Six generic follow-up suggestions were returned; token usage was null. No usable generated application was returned.
- Verdict: reject this failed candidate; stop continuation/regeneration pending shared inference investigation. Requested-model metadata is verified; successful generation and actual provider execution are not established by that metadata.
- Existing app code has hardcoded habits/streaks and no localStorage, IndexedDB, or Date usage. This is static comparison evidence only, not browser proof.
- Browser/app/persistence gates cannot run for this failed candidate. Existing example remains unchanged; audio remains on hold.

## Bounded root cause and independent fix

At 2026-09-08 12:27:47 UTC, `app-ai-worker` recorded OpenAI HTTP 400 for this exact task: `reasoning_effort` does not support `max`; supported values are `low`, `medium`, `high`, `xhigh`. Routing and billing preflight selected `openai/gpt-6-astra` correctly. The main streaming provider request failed before an application tool executed. Postprocessing subsequently succeeded through Mistral. This establishes an independent Astra provider metadata error, not a preprocessing failure.

Source chain: `backend/providers/openai.yml` sets Astra effort; `backend/apps/ai/llm_providers/openai_client.py` reads it and inserts it in `stream_payload`. No pipeline changes made. Existing `backend/tests/test_ai_ask_model_metadata.py` incorrectly pinned `max`; updated its assertion to `xhigh` while keeping capability `max`. Red: focused Astra assertion failed `max != xhigh`; green: all three metadata tests passed. Covered by existing `ai-model-routing.catalog.capability-recommendation-variants` assertion.

Owner of this bounded metadata/test fix: session 8999. Shared preprocessing/provider failure owner remains session 00b4. Runtime restart and real inference verification require explicit coordinator lease and target; neither performed. No blind regeneration. Task activity posting remains deferred to coordinator recovery.

Diagnostic correction: actual container is `app-ai-worker`; prior `app-ai` lookup did not inspect the worker. OpenObserve unavailable; bounded Docker worker logs supplied the provider error. No raw logs are persisted here.

## Coordinator runtime lease: safe scope rejection

Coordinator 4aa6 granted session 8999 a lease for `https://api.dev.openmates.org`, `app-ai-worker` only, loading deployed `a8162d6252cead765fb5fcec042f1562f5b397bc`.

Read-only preflight found the container's backend bind mount at `/home/superdev/projects/.openmates-runtime/product-stack/backend`. That clean shared checkout is at `ca026069e2f430568f7ff17e3bbbf7b0d76f5aa1`; its Astra configuration still reads `reasoning_effort: max`.

The supported `sessions.py docker restart` implementation calls `_ensure_product_runtime_checkout(refresh=True)`, which fetches and fast-forwards the shared runtime to latest origin/dev, then unions requested services with `_incoherent_docker_services`. It can recreate additional services to maintain backend source coherence. It has no exact-commit or strict service-scope flag. The scoped lease therefore cannot safely be executed through this workflow: refreshing shared bind mounts and restarting additional services exceeds app-ai-worker-only authorization. A plain worker restart would retain the broken source.

Outcome: stopped before Docker lock/drain/mutation; no runtime checkout changes, no restart, no lock held, no inference retry. Lease not consumed. Coordinator must arrange an explicitly approved coherent runtime update or a supported strictly scoped source-loading mechanism before Astra validation. No raw compose mutation or alternate-source workaround attempted.

## Expanded coherent runtime lease executed

Coordinator 4aa6 explicitly expanded the lease to coherent existing registered backend services and current dev source advancement. Ran `python3 scripts/sessions.py docker restart --session 8999 --service app-ai-worker --timeout 600 --health-timeout 180`. Operation `docker-f2f6ab2d` completed with all 13 selected existing backend services running and healthy. Supported workflow handled admission, Docker coordination and dependent-test drain. No database deletion, migration, new service, or production change requested.

Runtime checkout now `383bf1b51cc68b582eb620a6210aa04cfc8cfd36`; ancestry check confirms it includes deployed `a8162d6252cead765fb5fcec042f1562f5b397bc`. Reading `/app/backend/providers/openai.yml` inside `app-ai-worker` confirms Astra `reasoning_effort: xhigh`, `default_server: openai`. Session status confirms Docker lock released. Proceeding to one fresh approved-opening candidate after this verified correction.

## Follow-up blocker for shared provider owner 00b4

Fresh approved-opening real CLI candidate: chat `3a1b0f9b-7f34-43ec-8e74-98146648d9f9`, returned task/message `a55b49ff-4fd9-59ec-800b-7022cea2474d`. Assistant again returned `chat.an_error_occured` with GPT-6 Astra metadata.

Bounded `app-ai-worker` logs at 2026-09-08 12:58:06 UTC establish a different failure: `Invalid OpenAI reasoning_effort for model 'gpt-6-astra': 'xhigh'`. This is local validation before upstream inference. `backend/apps/ai/llm_providers/openai_client.py:29` defines `OPENAI_REASONING_EFFORTS = {"none", "low", "medium", "high", "max"}`; `_get_openai_reasoning_effort` rejects the provider-supported `xhigh` at lines 70–71.

Required shared-provider fix: allow `xhigh` through the adapter and extend existing payload tests to exercise actual Astra catalog metadata through stream/nonstream request construction. Existing metadata-only tests passed but did not test adapter compatibility. Owner is coordinator-assigned session 00b4; session 8999 has not edited overlapping provider code. No further regeneration until adapter correction is loaded. Browser/persistence proof remains pending because neither candidate produced an app.

Process finding: previous metadata-only verification missed an existing adapter allowlist. Smallest deterministic improvement is extending the existing provider payload test to consume Astra metadata, not adding prompt instructions. This belongs with the shared-provider repair.

## Adapter repair owned and completed by 8999

Coordinator clarified provider adapter ownership. Added xhigh without removing max; extended existing catalog payload cases across streaming/nonstreaming requests and refreshed the stale timeout stub. Both Astra cases failed before the fix; 18 tests passed afterward. Deployed `f42e33579b4ca4ae82f63117fdf5c17ed475c5fa` with lint, Specification, and pytest gates passing. Coherent runtime operation `docker-35da5536` completed healthy; runtime exactly f42e335 and both metadata and adapter support verified inside worker. Lock released.

Fresh real candidate `bdecd5e1-52d5-41d1-8666-24a3c97572bd`, task `87708aec-676b-5c98-b6af-1e7d5aeeb97f`, reached upstream but failed HTTP 400: function tools with reasoning effort are unsupported for Astra on Chat Completions; provider directs callers to Responses or reasoning none. No app generated. Unexpected Lisa/psychology routing added a mental-health disclaimer to the coding request. Preprocessing owner 00b4 should handle classification; no main_processor edits here.

Current adapter has no Responses path. Existing Luna tools exception sends reasoning none; extending it to Astra changes reasoning behavior and is not silently applied. Next coordinated scope must address reasoning plus tools compatibility. Task activity acknowledged blocker entry `65e4ebfceb56c24e9712b28252dd20cd840c778c52941797be3f1344db9e0e9a`; task is linked to this actual thread. No admission or browser/persistence pass claimed.

Process correction: one initial pytest invocation used canonical cwd and was discarded. Explicit workdir rerun supplied actual red evidence. Existing worktree instructions already require this; no new prose rule warranted.

## Scoped Responses repair proposal

Repository search found no Responses implementation to reuse (responses.create/stream, function_call_output, output event handling). `openai_client.py` explicitly documents deferred Responses support. Reuse the initialized AsyncOpenAI client, catalog upstream mapping, token accounting, existing tool parser, and unified text/ParsedOpenAIToolCall/OpenAIUsageMetadata boundary rather than replacing the main processing loop.

1. Add focused `backend/apps/ai/llm_providers/openai_responses.py`, called by the existing direct adapter for Astra. Preserve model gpt-6-astra and configured reasoning xhigh. Keep existing providers/variants on their current paths. Use explicit store=false; no provider-managed conversation or previous_response_id dependency.
2. Convert message content, assistant tool calls and tool results into Responses input items; flatten function definitions, explicitly retain strict=false where existing tools are non-strict, translate tool_choice and max output tokens. Preserve call_id exactly and map function_call_output to its originating call.
3. Adapt text deltas, completed function-call arguments, usage, incomplete/error/cancellation events into existing unified types. Emit each tool call once. Never turn failed/incomplete events into successful empty text or lose billable reasoning output tokens.
4. Preserve ordered opaque encrypted reasoning items across the tool-result continuation. Existing ParsedOpenAIToolCall has no such field. Gemini thought_signature history handling is an architectural precedent, not a compatible carrier. Add an explicit optional provider transport-state field and a narrowly coordinated history pass-through; agree the exact history-helper hunk with Sonnet because main_processor.py is its ownership. Keep preprocessing classification changes with Sonnet. Do not introduce unbounded global caches or hide state in tool arguments.
5. Extend existing provider tests for streaming/nonstreaming payloads, xhigh retained with tools, text then tool then result then final text, multiple tool calls, opaque item ordering, usage and failure propagation, store=false, and unchanged Sol/Luna paths. Verify actual dev REST/CLI/SDK behavior in required order after scoped deploy and coherent runtime refresh; then generate/review habit tracker on phone/laptop with persistence and proof gates.

Contract assessment: approved ai-model-routing ModelCatalogEntry.provider_reasoning requires supported values; catalog and exact-model assertions already require routable supported variants. A stateless transport compatibility repair preserving model, reasoning, auth, tool semantics, and existing privacy boundaries needs no new user-facing behavior Specification. This is conditional on an explicit audit of transport-state lifetime and existing history/cache serialization. New durable opaque state, provider retention, model substitution, or reasoning downgrade would require an exact Specification review before implementation. No such expansion is proposed or approved here.

Official sources opened: https://developers.openai.com/api/docs/guides/reasoning (stateless reasoning items with encrypted_content); https://developers.openai.com/api/docs/guides/migrate-to-responses (store=false, replay reasoning items, flattened function schema, explicit strict=false). This is a concrete implementation proposal, not passing Responses runtime evidence.
