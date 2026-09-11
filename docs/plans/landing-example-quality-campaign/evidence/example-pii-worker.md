# TASK-77 privacy example worker evidence

- Assignment: TASK-4 / example-pii, coordinated by TASK-5745.
- Session: `2fbf`; own distinct worktree `agent-2fbf`, verified with Git worktree metadata.
- Actual Codex thread: `01a080f6-92ce-7ed0-b196-4a3cc31208f0`.
- Base: `a9efbf0ee`; recorded 2026-09-08 UTC.
- Task connection and activity acknowledgement: pending; API returned HTTP 429.
- Coordinator instructed workers to stop Tasks API calls for at least ten minutes and await serialized recovery. No further task calls will be made independently.

## Source attempt

The supplied local Plan records no existing source chat for this assignment. Following the coordinator's authorization to proceed using local handoffs, invoked the assigned real source CLI with `chats new`, slug `privacy-email-phone-task77`, JSON output, and PII detection enabled by default.

Opening, verbatim:

> Help me write a message to a plumber. My kitchen sink has been leaking since yesterday, and I’m available tomorrow afternoon. Ask them to contact me at lena.hoffmann@example.com or +1 202-555-0147 to arrange a visit.

The CLI returned `Rate limited by settings API; retrying in 61s...` during preflight. Terminated this worker's command before its automatic retry. No successful source chat ID or response was returned. Check for a partial saved chat before retrying; do not assume termination implies no local/server state was created.

## Read-only preparation

- Existing `building-maintenance-email.ts` demonstrates the supported example message `pii_mappings` structure. Its older conversation does not satisfy the approved plumber opening and is not reused as candidate output.
- `create-example-chat-from-share.mjs` preserves `message.pii_mappings`; no renderer change is needed merely to retain email/phone mappings.
- Existing `pii-detection-flow.spec.ts` covers composer email/phone highlights, replacement, and chat reveal/hide controls. This is coverage discovery, not executed evidence.
- Required candidate review: both approved fictional contacts detected and replaced; useful plumber message; appropriate mate/model/language; source-generated follow-ups. Make no name/address detection claim.
- Required deployed review: full phone/laptop transcript and meaningful interactions, privacy replacement/reveal controls, landing and example entry, reload and composer follow-ups; applicable proof videos.
- Catalog owner owns registry/slide integration. This worker owns only candidate data, translations, and proof.
- Audio remains pending the user-approved speech pilot. No audio generation attempted.

## Pending recovery and handoff

Coordinator should serialize Tasks/settings API recovery. After recovery, inspect any partial chat for the assigned slug, then create or continue the real conversation and read each response before replying. Connect TASK-77 to the actual thread and post this milestone once with acknowledged delivery. Content, browser, audio, and user review remain pending; this example is not admitted or complete.

## Authorized single retry: source succeeded

Coordinator confirmed there was no earlier candidate and authorized one retry using normal CLI retry policy. No Tasks calls were made. The approved `chats new` command completed without a new 429; consequently no new Retry-After response exists to capture.

- Source chat: `5d90fb1c-2fa0-421b-96c4-5772c93e74fe`.
- User message: `b044c7b7-f3f8-4a29-9041-51b4d5d93824`.
- Assistant message: `a6baeaaa-7107-4c9c-bf43-2b94563bb8a6`; CLI client message `2ff95403-8a44-59b4-8aec-d53546370d00`.
- Mail embed: `aa8bee97-be75-43c8-b96c-779c4c36624f`.
- Actual routing: Makani / maker_prototyping, Gemini 3.5 Flash-Lite; English.
- Saved user text replaces fictional email with `[EMAIL_1_com]` and fictional phone with `[PHONE_1_147]`. The actual mail embed uses both same placeholders and preserves leaking-since-yesterday and available-tomorrow-afternoon details.
- Draft is useful and concise; six source-generated follow-ups exist. No additional conversational turn needed to improve this request.
- Share created through the CLI; temporary local share credential artifact `/tmp/task77-share.json` is intentionally excluded from repository evidence. Extracted source is `/tmp/task77-extracted.json`.
- Scaffold dry-run with `--require-follow-ups` passes: two messages, one embed, six follow-ups. Proposed slug `plumber-message-email-phone-privacy`; generated ID `example-plumber-message-email-phone`.
- Pricing extraction currently reports zero priced responses, although original completion reported 13 total credits. Do not claim extracted usage is complete.

### Publication dependency

Extracted messages contain no PII mappings. Source investigation establishes two relevant behaviors: `share.py::sanitize_shared_pii` intentionally removes `encrypted_pii_mappings` unless `share_pii` is true; `extract-shared-chat.mjs::decryptMessages` does not decrypt/return PII mappings. The CLI does encrypt and save mappings in `client.ts` when sending. Do not treat intentional share privacy as a defect or bypass it. A supported owner-authorized fictional-mapping publication path is needed to demonstrate original-to-placeholder reveal in the public example. No synthetic mappings or transcript edits were made.

Converter also always writes the shared example registry, owned by the catalog worker. Only a dry-run was performed; coordinator/catalog owner should coordinate candidate-only extraction/integration rather than this worker editing their registry. Browser and proof gates remain pending publication. No audio was generated.

### Limiter investigation

The checked `backend/core/api/app/services/limiter.py` explicitly has no global default limits and uses `get_remote_address`; Tasks and settings declare route-specific decorators. No `shared_limit` or application-wide bucket was found in inspected configuration. Workers can contend for a route's IP bucket, but source inspection does not prove the historical Tasks/settings 429s shared a global bucket. No rate limits or runtime settings changed. `client.ts::settingsGet` uses a fixed 61-second retry and does not expose Retry-After in its error. Historical Retry-After is unknown; do not label that retry delay as a server header.

Next coordinator handoff: connect actual thread and acknowledge this source milestone, coordinate fictional PII publication with converter/catalog owner, then deploy and perform full phone/laptop review. Source replacement evidence is established; public demonstration is not yet verified.

## Approved public fixture and smallest scaffold proposal

User explicitly approved public use of only `lena.hoffmann@example.com` and `+1 202-555-0147`; unrelated account mappings remain excluded. Existing `ExampleChatMessage.pii_mappings` and `ExampleChatEmbed.pii_mappings` support this public fixture. `exampleChatStore.ts` copies message mappings and registers embed mappings in the in-memory `embed_pii:<id>` store. No generic share-policy change is required.

Prepared `example-pii-public-fixture.json` alongside this record from the actual extracted source. Added only the two approved mappings to the actual user message and mail embed, using the placeholders observed in both saved contents. These are explicitly approved public demonstration sidecars, not a claim to have recovered owner-encrypted mappings. No account mapping store was read. A deep-equality check after removing the two added `pii_mappings` fields proves all source transcript, metadata, and embed content remain unchanged.

Fixture SHA-256: `a2448a5a8c41f871e9fe1134dc0f57fbb857093791dc910a64c8af5d97ecaecd`.

Validation: scaffold `--from-json <fixture> --slug plumber-message-email-phone-privacy --require-follow-ups --dry-run` passed. Direct inspection of exported `formatTs` output confirmed both approved message mappings survive but embed mappings are discarded.

Smallest proposal for the shared converter owner: add `pii_mappings: embed.pii_mappings || undefined` to `formatEmbeds` in `scripts/create-example-chat-from-share.mjs`, matching the existing message behavior. Extend its existing `scripts/tests/create_example_chat_from_share.test.mjs` coverage to assert that explicit approved fixture embed mappings survive and absent mappings remain absent. Do not read account mappings, modify share API defaults, or add implicit restoration. Catalog owner can then scaffold this exact reviewed fixture, own registry integration, and complete translations/deployment. An alternative without converter changes is to place the same approved sidecar on the final task-specific mail embed fixture, whose type and store already support it.

Public visual protection still requires deployed phone/laptop reveal/hide and mail preview/fullscreen verification. Prepared fixture and dry-run are not visual proof. No audio or Tasks API calls made.


## Implemented and deployed preservation fix

User explicitly authorized executing the one-field existing-format repair. Exact converter and test edit leases were acquired; interactions owner session e8c5 had no uncommitted diff in either file. Added `pii_mappings: embed.pii_mappings || undefined` to `formatEmbeds`. Focused test failed first with missing embed mappings, then all 16 converter tests passed. The test checks approved fictional email/phone mappings survive on messages and embeds, and absent mappings remain absent.

Scaffolded approved source fixture with `--require-follow-ups --featured false`; acquired exact registry and candidate file leases. Candidate is not admitted to the landing set. Deploy `9a51f28cf0462b2c7dbebc5dc171b512c261358f` pushed seven scoped files with passed lint, locale build and validation. Manual German translation follow-up deployed as `bfc3849ca22191ad8bf26647eab4c08dcb886f83`; example audit now passes. Other locales still contain English copies pending translation review; auto_translate rejected due to missing Gemini API credentials.

Verification requests: privacy spec job `c5924c72bb6cbd3e53baaab0f4858a26de9db0bf08195926acb7b2654dfb529b`; example load job `78257dd50a4ed565aa25aa70e0a149d3692593d5196fdcbcb60400ad7f373375` at 9a51f28. Both accepted by GitHub-isolated dispatcher; no passing result yet. Canonical proof workflow explicitly rejected start because no matching deployed passing run exists.

An initial public visual smoke ran before Vercel Ready and is invalid as candidate evidence: the old deployed example route showed a 500 Internal Error and JSON parse error, while the hash route remained on the landing page. Artifact: `test-results/visual-smoke/2026-09-08T12-59-32-806204+00-00/summary.json`. Viewed laptop example and mobile landing screenshots; do not count automated hash-route success as chat rendering. Vercel statuses for both pushed commits remain pending at this checkpoint; rerun only after deployment readiness. No audio generated and no share policy changed.
