# Apps skill latency investigation

Investigated 2026-10-02 for TASK-8996. This report recommends changes; it does not implement them. Source reference: published dev commit `dddd8603019aa93a83f294c660e56cfe61da337d`.

## Measured comparison

Executed two calls per surface, sequentially, using the same disposable development account and exact Web Search payload: one query, ten results, country `us`, language `en`, moderate safe search, tabloid filtering enabled, no relevance criteria. Semantic protection remained enabled. CLI used the globally installed package and a separate owner-only state directory; its temporary login was cleaned up afterward. No production or container changes.

The order was Web, REST, CLI, CLI, REST, Web. Login and metadata loading are excluded from request timings. These are a small live sample, not a production percentile benchmark; the first web call also overlapped initial account sync.

| Surface / phase | First call | Second call |
| --- | ---: | ---: |
| Web: submit to painted result title | 9.488 s | 5.747 s |
| Web: skill endpoint HTTP request | 4.541 s | 2.777 s |
| REST: complete parsed response | 3.369 s | 2.698 s |
| CLI: process start to JSON output | 3.553 s | 3.381 s |
| CLI: skill endpoint, parsed response | 3.013 s | 2.921 s |
| Web: new root lookup HTTP request | 0.465 s | 0.258 s |
| Web: processing graph save HTTP request | 1.102 s | 0.515 s |
| Web: finished graph save HTTP request | 2.993 s | 1.808 s |
| Web: all observed AES-GCM encrypt calls | 2 ms / 26 calls | 1 ms / 25 calls |

All six calls returned ten results. Browser timings use request completion plus a DOM observer and two animation frames for the first populated Website preview title. Encryption instrumentation records durations only, not keys or plaintext. HTTP rows can overlap slightly because response headers unblock fetch before the Playwright request-finished event. Browser-wide IndexedDB writes overlapped initial sync, so summed IDB request times must not be treated as Apps wall-clock time or attributed solely to retention.

Private timing-only evidence is in `test-results/apps-latency/20261002-comparison/summary.json`. The earlier deployed walkthrough is recorded in `test-results/apps-regressions/20261002-final-summary.json`: 13.769 s visible latency, 7.810 s skill HTTP, 1.584 s processing save and 2.494 s finished save. Conditions vary; the differences should not be presented as a measured improvement between software versions.

## Causes

The web has a serial critical path in `AppsWorkspace.svelte:240`: await processing graph retention, await skill execution, await finished graph retention, then set `inlineResultId`. The REST and CLI execution paths do not save the Apps graph.

In `appsWorkspaceResultsService.ts:619`, a new authenticated request also looks up its freshly generated root ID remotely before creating a key. That lookup returns 404 for a new request. Finished retention encrypts the graph locally, awaits the upload, hydrates the local embed store, then allows the UI to mount shared previews. Encryption itself was negligible in these samples. The additional web latency was approximately 3.0–4.9 seconds, dominated by remote persistence gates.

The backend receives an encrypted graph in one HTTP request but persists it through multiple serial Directus operations. `apps_workspace_results_service.py:165` reserves and validates the root/key, then looks up and inserts each missing child individually. Ten children therefore add approximately twenty child lookup/insert operations, plus root and key operations. This explains why a nominally single graph upload remains expensive; its exact database-stage contribution has not been separately traced here.

The earlier slow backend trace contained a 5.083-second `ai.provider` span and an approximately 1.030-second internal billing call inside a 7.785-second request. Published source strongly points to output safety scanning for the AI span: `call_app_skill` awaits `sanitize_app_skill_output`, Web Search always qualifies as external data, the scanner invokes the LLM with purpose `safety`, and Web Search has a five-second semantic scan deadline. The retained trace projection omitted attributes, so the actual model, purpose and timeout outcome are not confirmed. Do not describe this as a confirmed timeout or Brave search latency. Current matched calls returned in 2.7–4.5 seconds, demonstrating variability.

The scanner already batches result text into one model call. Parallelizing ten separate scans is not the missing optimization. Billing is awaited afterward; its authoritative balance/usage transaction must remain protected, but monthly/daily projections are currently awaited after commit and deserve separate timing.

## Recommended implementation order

1. **Remove remote saves from visible-result latency.** Prepare the new root/key and processing draft locally, then dispatch the skill without waiting for a remote lookup or processing upload. On API success, stage the encrypted finished graph in a durable account/team-scoped IndexedDB outbox and hydrate the normal embed previews locally. Render those cards below Run skill while a background uploader persists the exact graph. Use the existing preview registry and fullscreen components, preserving parent-only library behavior.
2. **Make background retention reliable.** Show saving/saved/save-failed state separately from execution success. Replay the same ciphertext, wrapped key and stable root/child IDs after reconnect or reload. Retry saving without re-running or charging the skill. Serialize updates for each root so a processing write cannot arrive after finished. Enforce account/team guards throughout, and reconcile linked existing assets without overwriting their local content. Mark saved only after acknowledgement. Any accepted asynchronous task IDs still need durable local recovery before treating dispatch as recoverable.
3. **Reduce graph save cost.** Batch child existence/ownership checks and inserts, retaining root reservation, ownership checks, immutable key wrappers, conflict handling and idempotent partial-graph repair. This improves save completion and server capacity after display is decoupled. Measure before changing encryption concurrency; AES-GCM was only 1–2 ms.
4. **Reduce the shared API floor.** Add explicit timings for provider fetch, semantic scan outcome/model, atomic charge and summary projections. Investigate a faster safety model/provider or a policy-versioned cache of vetted public result text. Move non-authoritative post-commit summary work into reliable asynchronous reconciliation if its timing justifies it. Do not disable default protection or defer authoritative credit charging as an optimization.

For the first two changes, a useful acceptance target is visible Website cards within roughly 300 ms of the API response, without awaiting any remote embed save. Based on these samples, that would remove most of the extra 3–5 seconds and roughly halve the observed web wait. This is a target and estimate, not yet a validated result. Further API improvements require stage measurements.

## Streaming and encryption

Streaming is compatible with the direction, but is not required to remove the current web penalty. Our Brave wrapper receives one completed JSON response, and the semantic scanner works on the complete batch. Wrapping that unchanged work in SSE would not produce usable search items sooner.

For skills with independently available result groups, an opt-in SSE contract could emit each group after the required validation and credit authorization, followed by completion. Keep the existing JSON endpoint behavior for REST/CLI clients. Measure time to first usable group, not connection establishment or progress messages. Handle cancellation, reconnect/deduplication and partial failures explicitly.

The client currently owns embed keys, encryption and key wrapping. The backend stores ciphertext. It cannot simply create the same encrypted embed graph from raw results after responding without receiving client ciphertext or changing the encryption trust boundary. The proposed client outbox preserves that boundary: results become visible locally while the client uploads ciphertext in the background. If later server-side persistence is decoupled after ciphertext acceptance, it needs a durable job/acknowledgement contract rather than an in-process fire-and-forget task.

## Verification for implementation

Extend focused Apps coverage for cards before save acknowledgement; save failure preserving successful cards; retry without provider redispatch; reload/reconnect recovery; ordered processing/finished updates; and personal/team isolation. Retain native preview/fullscreen and parent-only library assertions. Run component and route checks through isolated CI, then repeat the matched dev timing protocol. This investigation made no product code changes and needs no additional product CI run.
