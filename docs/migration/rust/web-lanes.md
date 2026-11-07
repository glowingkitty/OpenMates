---
status: active
doc_type: reference
audience:
- contributors
last_verified: 2026-11-07
key_files:
- docs/migration/rust/web-lanes.yml
- docs/migration/rust/overview.yml
---

# Web client logic to Rust: wave 4 lane plan (2026-11-07)

Goal: move ALL client-side logic of the web app and shared client code (frontend/packages/ui/src, frontend/apps/web_app/src) into shared Rust in the one shared Worker. Svelte keeps UI/DOM and the browser APIs. The UI stays unchanged. VITE_OPENMATES_RUST_CORE stays default off, and flag-off output stays byte-identical.
Sources: .claude/rules/cli-sdk.md, docs/architecture/platforms/rust-migration-status.md, sharedWorkerUnits.ts, plus a LOC scan of the tree on dev (f725997112).
Machine-readable plan and live lane status: web-lanes.yml (this file is the narrative; statuses live in the YAML).

## 1. State today
- Installed units (9/11): core, crypto, auth, apps, embedData, embedWrite, search, transfer, sync.
- Planned and reserved: chatState, ws.
- Running lanes:
  - drafts: services/drafts/*, browserDraft*.
  - search snippet perf: web_search*, browser_search_pii.
  - sync policy + key-write admission: chatSyncMerge, phased retry, the key guards, rustCore/sync/*.
  - zip/account export: zipExportService, accountExportService, transfer unit.
  - send latency: sendOperation/sendProtocol/originalSavedChatSender, browserWsLink, crypto send path.
  - send-correctness: coreUnit.ts, sessionBroker.ts, rustChatHistoryBootstrap.ts.
  - memory/RSS: build, bindings lib.rs exports, bench helpers.
- Rust already present but not served by any unit:
  - packages/openmates-rust/src/chat_state/* (receipts, bookmarks, highlights, management, hidden, fork, projects).
  - browser_chat_state*.rs.
  - ws_link/* (machine, router, envelope, feedback).
  - A page adapter, rustCore/chatState/chatStateAdapter.ts, that is wired only to its test.
- Size: about 103k LOC of top-level services/*.ts files, plus db/ 7.6k, encryption/ 2.7k, stores 17k, utils 8.5k, message_parsing 8.5k, and about 38k LOC of non-UI TS under components/enter_message and 27k under components/embeds (mostly preview fixtures and renderers). frontend/apps/web_app/src has about 4.9k LOC of TS, mostly the Rust host plus SSR routes (server code, out of scope).

## 2. Inventory of the remaining TS client logic

Columns: approximate LOC; the split between pure logic and browser IO; dependencies; risk (A = needs user approval before turn-on: crypto/auth/IDB writes); target unit. Each row names its lane.

| Area | Files (main) | LOC | Logic / IO split | Depends on | Risk | Target unit -> lane |
|---|---|---|---|---|---|---|
| Chat read state, bookmarks, highlights, management, deletions, Project placement | visibleMessageReceipts, chatReadState, messageBookmarks, handlers/sendersMessageHighlights, db/messageHighlights, utils/messageHighlights, sendersChatManagement, pendingChatDeletions, chatProjectService, chatMenu* | ~2.3k | 80/20 (WS send, IDB) | crypto unit (chat key) | A (encrypted writes) | chatState -> chatstate-core |
| Hidden chats, forks | hiddenChatService, hiddenChatStore, forkChatService, forkProgressStore | ~1.2k | 85/15 | chatstate-core, crypto | A | chatState -> chatstate-hidden-fork |
| Inbound chat updates, core sync, routing | chatSyncServiceHandlersChatUpdates (2742), ...CoreSync (1431), chatSyncService (3887) routing, guards, Webhooks/AgentContext/FocusPhases, phasedSyncStateStore | ~9k | 70/30 (IDB/store writes) | sync-policy lane | A (drives IDB writes) | sync -> sync-inbound |
| AI stream assembly, recovery | chatSyncServiceHandlersAI (6243, non-embed), ...Recovery (1900), pendingAIResponses, fastAdmission*, chatRecoveryVersion*, utils/chatCompletionRecovery, message_parsing/assistantActivity* | ~8k | 75/25 | sync-policy, embeds-2 (done), ws-unit for hosting | A | sync + ws -> ai-stream-recovery |
| Embed read/resolve/version/content | embedResolver (1119), embedStore (4379, rest), embedDiffStore, embedStateMachine, embedRefIndex, embedVersionReconstruction, embedLinkUtils, sheet/mindmap/docs content, embedSenders, audioEmbedCrypto | ~9k | 80/20 | embedData/embedWrite | A only for audio crypto | embedData -> embeds-3 |
| Chat/message persistence policy and caches | db/chatCrudOperations (2343), db/messageOperations (2296), db.ts (3102), chatListCache, chatMetadataCache, recentChatWindowCache, messageWindowPruning | ~11k | 60/40 (IDB) | drafts, send-correctness | A (IDB writes) | core -> persistence |
| Send preparation, preflight, offline outbox | sendersChatMessages (4052), sendHandlers (3109, non-UI), prepared*ForSend, projectFocusSendPreflight, model selection, offline*, db/offlineChangesAndUpdates, sendersSync | ~10k | 75/25 | send-perf | A (outbox writes) | core -> send-prep-outbox |
| WebSocket transport | websocketService (1720), wsSpans, connection/serverStatus stores logic | ~2.2k | 50/50 (WebSocket object) | send-perf, send-correctness | A (token) | ws -> ws-unit |
| Chat/master key lifecycle | ChatKeyManager (1599), db/chatKeyManagement (1029), cryptoKeyStorage, cryptoService (1284), Message/MetadataEncryptor, mediaEncryption | ~5.7k | 70/30 (WebCrypto, storage events) | sync key-write admission, send-perf, auth-rest slice 0 | A | crypto -> keys |
| Share links, short URLs, guest/incognito | share*/shortUrl/embedShare/sharedChat*, shareMetadataQueue, anonymousChat*, incognitoChatService, share routes | ~5.4k | 75/25 | keys (installer line) | A | crypto -> share-guest-crypto |
| Remaining auth flows | authSessionActions (1448), authLoginLogoutActions (992), authMisc, signupState, pair*, passwordV2*, recoveryKeyUtils, tfa | ~4k | 65/35 (fetch, passkey API) | auth unit | A | auth -> auth-rest |
| Settings, memories, personal data, user DB | chatSyncServiceHandlersAppSettings (3117), db/appSettingsMemories, appSettingsMemories*Store, personalDataStore, topicPreferences*, savedEmbedMemoryService, userDB (1752) | ~9k | 70/30 | crypto | A | new `settings` -> settings-memories |
| Composer logic (PII, mentions, paste, code/url embeds) | piiDetectionService (1171), mentionSearchService (1163), codeEmbedService (1015), urlMetadataService (965), embedHandlers (2282), pasteClassification, fileHandlers, xlsxSheetConverter | ~9k | 70/30 (fetch, File) | search-snippet-perf (PII) | low | new `composer` (pre-bind) -> composer |
| Message parsing / block model | message_parsing/* (8.5k), enter_message/utils/markdownParser (1653) | ~10k | 95/5 | none (stream integration after ai-stream-recovery) | low, HIGH perf risk | new `parse` (pre-bind) -> parse |

Parked for wave 5 (inventoried, not in this wave's 14 lanes):

| Area | Files | LOC | Notes |
|---|---|---|---|
| Work: projects, tasks, teams, plans, workflows, apps workspace | projectService (1827) + project* (~5.7k), appsWorkspace* (~2.6k, partly Rust apps unit), userTaskService (1084), teamService (734), userPlanService (1177), workflow* (~1.2k), workflowWorkspaceStore (774) | ~15k | Reuse CLI Rust (project_task_sync, teams, tasks); not on a gated flow. Strong candidate to lead wave 5, in two lanes. |
| Suggestions / inspirations | dailyInspirationDB (1103), dailyInspirationStore, db/newChatSuggestions (605), continueCarouselService | ~2.6k | A (encrypted). Reuse sdk inspirations / new-chat-suggestions Rust. |
| Navigation, deep links, notifications | deepLinkHandler (727), chatUrlService, internalLinkValidation, chatNavigationStore, settingsRoutes, pushNotificationService (605), notification visibility/receipts, reminderNotificationContext | ~3.5k | Push API and router stay; policy moves. |
| Voice / speech | voiceCall* (~3.7k), assistantSpeech* (~2.5k), audioRealtimeTranscription | ~6.5k | Media/WebRTC stay; turn-taking, queue and cue state machines move. |
| Connected accounts, code runs, notebooks | connectedAccount* (~1.5k), codeRun*/notebookRun* (~0.8k) | ~2.3k | A for the OAuth token broker. |
| Telemetry / debug | debugUtils (4958), clientLogForwarder, logCollector, userActionTracker, issueReportSubmission, e2eTestHooks | ~7.7k | Redaction policy moves; dev-only tooling may stay in TS (needs a user decision). |
| Static catalogs | data/appsMetadata, modelsMetadata, embedRegistry.generated | ~7.7k | Generate from one source shared with Rust; no runtime logic. |

Stays in TS (UI/browser): *.svelte; the TipTap renderers GroupRenderer.ts (8030) and AppSkillUseRenderer.ts (6174), with a logic audit later; reactive stores as view state; the i18n setup; theme/uiFont; frame-timing render schedulers; codeHighlighting; media/WebRTC; Push; file pickers; clipboard; demo_chats static content; SSR routes in web_app.

## 3. Ranked lane list (wave 4)

Rank = priority (gated user flows first: cold start, open chat, send/stream, embed ready, search), then readiness.

| Rank | Lane | Size | Deps (hard) | Wave | Unit / namespace | Approval to enable |
|---|---|---|---|---|---|---|
| 1 | chatstate-core | M | none | A (now) | chatState (install) | yes |
| 2 | embeds-3 | M | none | A | embedData ops | audio crypto only |
| 3 | sync-inbound | L | sync-policy lane | B | sync ops | yes |
| 4 | ai-stream-recovery | L | sync-policy lane; wire stream after ws-unit | B | sync ops + ws/streamOps | yes |
| 5 | persistence | L | drafts lane, send-correctness lane | B | core ops | yes |
| 6 | send-prep-outbox | L | send-perf lane | B | core ops | yes |
| 7 | ws-unit | L | send-perf, send-correctness | B (land last of the transport work) | ws (install) | yes |
| 8 | keys | L | sync-policy key-write admission, send-perf, auth-rest slice 0 | B | crypto ops | yes |
| 9 | parse | L | none | A | new `parse` | no |
| 10 | settings-memories | L | none | A | new `settings` | yes |
| 11 | composer | M | search-snippet-perf lane | A/B | new `composer` | no |
| 12 | auth-rest | M | none (slice 0 first) | A | auth ops | yes |
| 13 | chatstate-hidden-fork | L | chatstate-core | C | chatState ops | yes |
| 14 | share-guest-crypto | M | keys (installer line) | C (Rust/vectors can start in A) | crypto ops | yes |

Dependency order:
- Wave A, start now (no running-lane blockers): chatstate-core, embeds-3, parse, settings-memories, and auth-rest. auth-rest lands slice 0 within its first hours. composer joins if the snippet-perf lane has landed. share-guest-crypto may start on Rust and vectors only.
- Wave B, start as each running lane lands:
  - sync-policy lands: sync-inbound, ai-stream-recovery.
  - drafts and send-correctness land: persistence.
  - send-perf lands: send-prep-outbox.
  - send-perf and send-correctness land: ws-unit.
  - sync-policy, send-perf and auth-rest slice 0 land: keys.
- Wave C: chatstate-hidden-fork after chatstate-core; share-guest-crypto lands after keys' registry line. ai-stream-recovery's stream wiring follows ws-unit.
- Concurrency: at most about 8 lanes at once (host, disk and CI capacity; wave 3 ran about 13 and hit DiskWait). Suggested first batch: ranks 1, 2, 9, 10, 12 plus whatever B lanes are unblocked.

## 4. File ownership and conflict avoidance
- Each lane owns the files named in its brief, plus only new files (new ops files, new Rust modules, a new bindings file).
- Giant files each have exactly one extract-only owner:

| Giant file | Owner lane |
|---|---|
| chatSyncServiceHandlersAI.ts | ai-stream-recovery |
| chatSyncServiceHandlersRecovery.ts | ai-stream-recovery |
| chatSyncService.ts | sync-inbound |
| chatSyncServiceHandlersChatUpdates.ts | sync-inbound |
| chatSyncServiceHandlersCoreSync.ts | sync-inbound |
| chatSyncServiceHandlersAppSettings.ts | settings-memories |
| sendersChatMessages.ts | send-prep-outbox |
| sendHandlers.ts | send-prep-outbox |
| db.ts | persistence |
| db/chatCrudOperations.ts | persistence |
| db/messageOperations.ts | persistence |
| embedStore.ts | embeds-3 |
| embedHandlers.ts | composer |
| cryptoService.ts | auth-rest for slice 0, keys afterwards |

- Expected pairwise overlaps, all on hot op tables only:
  - persistence and send-prep-outbox: core unit dispatch.
  - sync-inbound and ai-stream-recovery: SYNC_OPS.
  - keys and share-guest-crypto: cryptoUnitInstaller.ts.
  - parse, settings-memories and composer: sharedWorkerProtocol.ts (appended namespaces).

## 5. Hot files and the serial landing protocol
Hot files:
- sharedWorkerProtocol.ts, sharedWorkerUnits.ts.
- packages/openmates-browser-bindings/src/lib.rs, packages/openmates-rust/src/lib.rs, mod.rs files.
- config/sdk-capabilities.json, config/cli-command-catalog.json, docs/architecture/platforms/rust-migration-status.md (generated).
- Per-unit op tables: SYNC_OPS, cryptoUnitInstaller.ts, authProtocol.ts, embedDataProtocol.ts, the chatState op table, coreUnit.ts/workerDispatch.ts.
- Bench/build files, owned by the memory lane.

Protocol (also in web-lanes.yml):
1. All work goes into owned and new files.
2. Hot hunks go into ONE final registry commit.
3. Before that commit, run `sessions.py worktree refresh-base`, then `sessions.py edit-lease acquire --file <hot files>`. If another lane holds the lease, wait once.
4. Regenerate generated files with their generators, then run the matrix validator.
5. Run deploy with ONE --only list, then wait-deploy, then release the lease.
6. When lanes are ready at the same time, they land in rank order.
7. New namespaces are appended to the end of SHARED_NAMESPACES, in landing order.
8. Every new namespace must prove it does not leak into the flag-off build.

## 6. Gates for every lane
- CI: rust-check all, rust-wasm, vitest (no new failures vs the baseline), sdk-conformance (pub symbols are classified), and the lane's flag-on E2E specs.
- web-rust-core-bench: 1 Worker / 1 WASM, zero main-thread WASM, no rust_worse verdict on the gated flows, no per-reload memory growth.
- Flag-off byte-identical.
- Lanes marked approval_to_enable land behind the flag and are proven in CI only; the user approves turn-on explicitly.
