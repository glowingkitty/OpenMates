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
