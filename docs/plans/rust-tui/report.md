# Native Rust CLI/TUI migration and performance evidence

## Current source-qualified evidence — 2026-10-24

**Performance regression is an acceptance blocker.** The user explicitly requires
end-to-end CLI/TUI performance at least matching TypeScript, with noticeable
improvement expected. TASK-8974 owns this gate; rollout acceptance remains open.
Lower CPU/RAM and renderer improvements cannot clear slower application workflows.

The Linux essential native milestone is **verified**. Source
`3a962e77b1277e8a64c36af3fefbd72859c1bb8e`, tree
`db2be0ac83cb484f43aacf22f6bb1fe12a110d07`, passes all **12 essential gates** in
[run 40065596506](https://github.com/glowingkitty/OpenMates/actions/runs/40065596506),
request `0b77be3590d211c4ecaec620e9b43bb5574b79434a09f09a7a9ee1671467b24c`.
All **467 native tests** pass, with **four intentional integration ignores**.
Auth, incremental saved sends, JSON continuation, independent encrypted readback,
live sync, reconnect/replay, CLI/TUI cancellation and restart recovery all pass.
Retrieval and evidence upload exit0; owned cleanup confirms zero containers,
zero volumes and removal of private account files. Two real CLI/TUI terminal
videos are uploaded without reconstruction. The [stage receipt](essential-native-stage-status-2026-10-23.json)
retains all twelve check names and recording object identities.

**Browser/WASM admission is achieved.** TASK-9393 is done and TASK-9558 is
in_progress. TASK-1233 remains open for installed preview refresh and actual
macOS acceptance. Exhaustive CLI parity, SDK publication gaps, separate self-host
readiness and macOS do not block browser work. The installed source1b preview and
npm command remain alongside each other; no automatic replacement or retirement
acceptance follows from this Linux milestone.

The later candidate `c07dfc028411cde9e67386c039a6427602ba61ae`, run
`40086647315`, repeats all eleven functional checks successfully, then fails at
`capture_tui_exit` while creating the updated terminal recording. Closed
diagnostics identify the existing ten-second `open-chat` checkpoint wait while
the terminal remains alive. Actual input delivery, terminal geometry and final
screen are not retained, so the cause remains unproven. Its final owned cleanup
acknowledgement is not reached; recovery files are retained and `cleanup_failed`
is false. Normal retrieval/upload exit zero. The earlier complete pass does not
establish refreshed-package acceptance.

The latest SDK checkpoint is source
`2236d0bcf96dd6468121ebc663db6a587033f277`, tree
`7cf310b6df54e362d72ba070859aac57458fb010`,
[run 40083808463](https://github.com/glowingkitty/OpenMates/actions/runs/40083808463),
request `2bfb6afbe0e55a51ef0a5888d676e5c33526cd967dc185bebbd837f23c0056c8`.
Its **408 SDK library tests**, **36 binding tests**, **54 adapters/615 outcomes**
pass with 2,104 held inputs, native artifact/load identity and verified cleanup.
Normal retrieval and evidence upload exit zero. This includes the HTTP-deadline
regressions; it establishes native SDK conformance, not browser runtime behavior.
The working SDK portability and eleven-file browser binding foundation remain
**unverified for browser use**. Source `feedd80d58b86cef856c81ed643d38ccafff2b90`
passes all eleven native build/unit/binding stages, then stops before conformance
adapters because eleven browser exports need capability classification. Those
exports are now explicitly classified under the existing partial session-client
capability, with a reviewed release-gate pin update. No capability was promoted.
The timer, request-timeout and strict HTTP-deadline corrections in source2236
now pass the managed WASM compilation gate in run `40085423342`, request
`84e8a17b762c9f5549cea473c478bed5fe29cc2be5cd87bd1efacf037407bd66`.
The standalone raw WASM artifact is **1,466,442 bytes**, SHA-256
`d63f5b7454ae35618ef5a086e41b9fa08cf1915c58b6817e45f14020d0bf64eb`.
Source and cleanup checks pass; normal retrieval/upload exit zero. This follows
the earlier successful compiler stages but rejected artifact in run40083810901:
reviewed harness444 safely exports an independent file and verifies both input
and output identities after the final read. Raw module size is not compressed
download size or matched full-web performance. Real wasm-bindgen loader packaging
and browser runtime tests remain required; no browser runtime pass is established.
All **156 SDK capability gaps** remain publication blockers; the older 615-outcome
result does not cover these changes. The web application still uses its existing
implementation, with no active Rust Worker or authentication replacement.

**Security follow-up blocks new installation and release acceptance.** A fresh
2026-10-24 audit of all four lockfiles finds `crypto-bigint 0.5.5` affected by
[RUSTSEC-2026-0387](https://github.com/RustSec/advisory-db/blob/21d909e4c8bd4e14c7aea58bf980c881a0053ab1/crates/crypto-bigint/RUSTSEC-2026-0387.md).
All scans use the same clean, freshly fetched RustSec commit with no ignores or
target filters. The dependency-chain fix and actual Ristretto-path reachability
assessment remain open. Passing functional tests and the earlier audit snapshot
do not clear this new finding. Details remain in [security.md](security.md) and
the [existing audit record](dependency-audit.json); this does not change the 156
capability-gap count.

**Fresh Rust self-host readiness passes; TASK-5702 is done.** Source
`83e6345e607ae96c4a5895cca93474e1226448b6`, tree
`1044a2848f89741cbcaf359f00ae28e7ac3876b6`, passes the matching source, image and
legacy scopes in runs `40088488008`, `40088490965` and `40088493475`. The strict
aggregate verifies identical source/tree, harness, recipe and input-set identity.
Source has seven passing steps, image eighteen plus four passing browser cases,
and legacy eight. Each scope confirms zero owned containers/volumes and private
account removal; normal retrieval and upload exit zero. Individual recipe-target
receipts retain `coverage_complete=false`; acceptance comes from all three
together. Only image has full browser-spec coverage. The
[existing self-host record](selfhost-ci-2026-10-22.json) preserves the earlier
deadline failure and the new aggregate. This does not clear performance, security,
SDK publication or retirement gates.

The latest [signed-in partial CLI comparison](application-benchmark.json) is
source `c07dfc028411cde9e67386c039a6427602ba61ae`, run `40086645265`, request
`c9906622c32ab94a18e61c8abdfe4081b4803d741c6c35938d56a60c3c2bef8a`.
Its CLI subreport passes all thirty samples: five fresh processes per language
and command, with warm independent profiles, two chats and twelve messages.

| Command | Rust median wall | TypeScript median wall | Rust median CPU | TypeScript median CPU |
|---|---:|---:|---:|---:|
| whoami | 670 ms | 937 ms | 34 ms | 575 ms |
| chats list | 4,765 ms | 526 ms | 46 ms | 528 ms |
| chats show | 3,301 ms | 2,940 ms | 45 ms | 692 ms |

Rust largest-process high-water memory is about22–26MiB versus136–156MiB for
TypeScript; this is not aggregate tree peak memory. CPU includes the waited owned
process forest; each CLI sample confirms shutdown. The overall comparison fails
at the 1,200-second Playwright-process limit; TUI verification collects no valid
samples. Cleanup confirms zero containers/volumes and private account-file removal;
normal retrieval/upload exit zero. These are provisional CLI observations from a
failed overall run, not complete-application acceptance or a broad speedup claim.

Source inspection identifies duplicate Rust recovery-discovery/list sync, omitted
CLI cache restoration before initial empty-cache persistence, and repeated whoami
admission. The pinned TypeScript warm list uses its retained cache. Cache parity
and redundant work must be corrected while preserving security and recovery;
the different cache behavior does not waive the performance floor. The conditional
three-second metadata-discovery fallback has not been attributed in retained logs.
Earlier source `d76b74b2b351c897e826619064b620bd657d9a94`, run40072614278, stopped
before samples at the descendant observer. The reviewed owned-tree meter now
accounts for the reference helpers and requires complete shutdown. Historical
help/version and renderer measurements remain separate.

The stronger [legacy web BEFORE checkpoint](web-before-performance-2026-10-23.json)
now passes the exact controlled-cache case on its first attempt in run
`40072459544`, source `5fbd6ca2a375554fba4d790227945a5489cb11c4`, tree
`17efdbc17e480a97bb3d868c4d3fcfc21809036e`. Login reaches an explicitly selected,
real decrypted six-message fixture chat and usable editor in **20,299 ms**;
cold-fill and two warm reloads reach that same endpoint in **7,742 / 6,570 /
6,663 ms**. Every snapshot contains **23 chats/20 persisted messages**, with six
loaded/source messages. JavaScript transfer is **4,414,603 / 300 / 319 bytes**;
no `.wasm` resource is observed on this route. Stable reported-process CPU deltas
are **12,460 / 10,720 / 10,870 ms** for reloads; qualified RSS endpoints remain in
the evidence rather than being called peak RAM. This one-case run has zero skips,
failures or retries, verified cleanup and uploaded recording object identity.
The preview/served-entry receipt binds the legacy source, while attachment mode
and asset-inventory claims remain unspecified. Earlier zero-message observations
remain separate history. Only one cold and two warm samples were measured; the
required cached-replay regression, broader streaming/sync responsiveness, isolated
WASM initialization and matched Rust/WASM AFTER remain open. This baseline excludes
the inactive Worker foundation and establishes no Rust performance advantage.

The dated checkpoints below preserve historical, source-specific evidence.

## Installed preview and historical essential-stage checkpoints — 2026-10-23

The side-by-side Rust preview is **installed** as `openmates-rust` at
`~/.local/bin/openmates-rust`, a direct symlink to the Cargo-installed ARM64 ELF.
The installed npm global `openmates` link, inode, mode and target bytes remain
unchanged, as do ten older native pins and two SDK libraries. The preview uses
`~/.openmates-rust`; installation used only explicit empty-state help/version
smokes and did not log in, migrate credentials or access a real account.
It reports local version `0.1.0`, not a published development prerelease.

The [curated installation proof](parallel-rust-preview-install-2026-10-23.json)
binds source `1b2813974be468b4e37bfdebc0500abb0c82cf0a`, tree
`4c3dbb6a71e0f197a57b10fe5ce6da027d3c5f17`, passing 558-path source preflight and
independent dirty/untracked/blob census, 188 held compiler/embedded/three-lock
inputs, and 148 actual release dep-info inputs. The independent installed ELF is
24,453,464 bytes, SHA-256
`cff8f6854b97e51cbb879b7392e50f0f628d1ede5490b6f94405a546bf08af8c`, mode 0700
with one link and its own inode. Cargo local-path install took 277.07 seconds with
minimum 34.1606 GiB free under the 30.75 GiB guard; this cache-assisted time is not an
application or clean-build performance benchmark. All four isolated installed-ELF/
alias help/version smokes pass. The exact preview/alias persistent exclusive lease
was granted and released. Original private receipts remain retained; curated proof
contains no credentials or private environment values.

The [stage evidence](essential-native-stage-status-2026-10-23.json) records the
resolved clipboard-win 5.4.1 yank through the narrow 5.4.3 lock correction (native lock
`309a5e50729a0bb15689a44f39800b17d449affece7167faebb7704ba31e3de6`). Fresh audits
of all three crates report zero vulnerabilities, zero unsound and zero yanked
packages; three native maintenance notices remain visible. The retained Rust SDK checkpoint passes 316
tests including 14 source-host regressions and strict all-target Clippy/fmt; newer
recovery source is outside that pass.
That host prerequisite is parked off the essential critical path: no filesystem
host, FFI/facade/all-three conformance or product proof is implied. Goal-chat's 35
focused native tests and strict checks remain bounded local evidence.

The trusted harness's official Node acquisition was published as 1edab52 by the
coordinated other chat. Our FD cache anchors and closed early-failure envelope
(candidate 26c990) are deployed as `4a14fa15eea8a42eff490bb1723f573afb9e9335`
across six paths, with 11 Node and 41 Python checks plus Ruff/Specification/lint gates
passing. The generic world-write guard and raw suppliers are unchanged. Current
source 1b request `ddc01465815219a4bc4da6636f2d042d1463e07bc6571c09554890db4cb811c3`
completed as [run 39992845748](https://github.com/glowingkitty/OpenMates/actions/runs/39992845748).
Node startup, native SDK/protocol checks, fifteen authenticated terminal checks,
browser pairing and Workflow unlink pass. Both attempts then fail authenticated
benchmark preparation with `preparation_child_failed`, before metrics or draft
proof. The child’s precise refusal was discarded by the old helper and remains
unknown. The source-qualified result does not prove essential live sync/recovery.
Guarded artifact retrieval initially refused for capacity, then succeeded on the
normal retry. Cleanup verifies zero remaining containers/volumes, removed private
account files and two removed allowlist identities. The receipt’s evidence command
exits zero: twenty videos and two images uploaded, with no upload failures.

The separate preceding 034 retry (request prefix 955847, run 39989316185) failed
`source_mode`. Its observed Node v24.21.0 x64 inode had mode 00777, current owner,
one link, stable canonical identity and matching process identity. A diagnostic
was written, but the coordinator's one retrieval failed identity validation:
there is no approved normal receipt, upload or cleanup proof. The earlier
run 39986942686 retains its unknown-mode qualification; later observations are
not backfilled into that run.

Current integrated source `c6504bc` reaches native release compilation in CI
`40029480804`, then its library run passes 385 cases and fails seven new saved-read
recovery fixtures. The product gates and binary actor tests are not reached. An
independently reviewed two-file fixture correction preserves production guards
and assertions; its Rust rerun is pending. Current self-host run `40032082045`
also builds both CLIs, then stops after successful npm installation because the
published executable is unavailable on PATH. Its install/browser flows are not
reached. Both runs verify cleanup and complete evidence upload.

The [partial legacy web baseline](web-before-performance-2026-10-23.json) is now
retrieved with verified fixture, production inventory and served-entry bindings.
All three page-load checks pass first attempt. Renderer replay first exceeds the
existing 50 ms maximum-operation guard at 61.7 ms, then passes on retry with an
11 ms maximum. Both attempts are retained. Every resource snapshot reaches the
default 250-entry buffer; transfer/count totals are lower bounds. A bounded
pre-navigation buffer and overflow correction passes nine inert checks, with
actual browser verification pending. These measurements do not cover the full
approved web comparison or establish any Rust speedup.

Corrected source `b1e24c099161b709509f463e6e3f65cb2da201f5` passes preflight
and a 602-path independent byte/mode census. Native essential and self-host
reruns are queued, alongside corrected resource capture and authenticated startup
measurements. Seventeen collector and nine self-host inert checks pass; queued
checks do not establish product success.

The corrected native unit stage in run `40034462564` passes **458 tests**, with
four integration cases intentionally ignored. The product flow then stops before
any send: the harness changed app Origin `localhost:5173` to `127.0.0.1:5173`,
which the backend correctly rejects. The reviewed harness repair passes eleven
JavaScript and thirty-three Python checks; backend CORS and application logic
are unchanged. All twelve product gates still need actual verification.

The isolated SDK lane is deployed with protected execution and strict receipt
validation. Its first run stops at Node dependency setup before Cargo. The raw
setup log expired privately, so its precise cause remains unknown. A verified
npm PATH omission and closed setup diagnostics are corrected in `cfa47ff6`;
attempt two is queued. All 156 release gaps remain open.

The essential gate remains **OPEN**. Reviewed monitor, recovery, CLI and TUI
activation are integrated in source. The whole Rust SDK library now passes **382
release-profile tests**, including all 24 new recovery and 42 live-monitor cases.
The first monitor attempt passed 41/42: its failing case constructed a hint the
real decoder cannot produce. Independent review confirmed the fixture defect;
that case now uses the real coalescer and preserves cancellation, chat/version
and Team-switch assertions. Production behavior was unchanged by the correction.
The full run holds all 796 source/lock/pin/library inputs. Two later Rustfmt-only
changes sort/wrap existing reexports and reflow an assertion. These are unit and
synthetic-protocol results, not application performance or product evidence.

The native pump performs bounded cold-start/reconnect discovery before fresh
views, then follows explicit reads, hints and deferred work. It preserves exact
uncertain ciphertext, rotates saved/new work fairly and quiesces corrupt local
records without deleting them. Native adapter seven-case, actor twelve-case,
UI eight-case, new CLI fourteen-case and binding ten-case checks remain unrun.
Two native test admissions stopped at the unchanged disk floor **before Cargo
started**, including one after successful evidence upload. Debug compiler caches
remain unused and disposable only by parent7d08. Reviewed isolated GitHub unit coverage is
queued with the essential product flow without widening trusted limits. Team-direct end-to-end completion
also remains unproved. The installed preview is still source1b; these source
changes do not update that executable or establish native acceptance.

The same integrated source `c6504bc4912c91971ae7e8b66cac0474e9eebab7` is also
queued for current self-host installation, update, admin, passkey and recovery
coverage (request `72acdeb267872ff21e82344785075a2b2e87ac2efbd8fbdb2644595fbfcf4219`).
Its older successful source2bc run remains retained; a current-source pass is open.

The standalone twelve-case essential E2E and direct native CLI/TUI capture harness
are integrated after reviewed functional/visual patches. Twenty Python and twelve
Node inert checks pass; all twelve product gates and both recordings remain UNRUN.
The old benchmark target is preserved. Its closed diagnostic has 26 inert tests;
six strict TypeScript diagnostics match source1b exactly, so no whole-helper strict
pass is claimed.

The separate diagnostic request
`48f4fb7fa6a5b31def11b27d123b92581f217d11a0ecceb297c9c1429582eca4`, source
`5128b2bd167d3704c5984df5f22b31d6803e346b`, fails in
[run 40014172598](https://github.com/glowingkitty/OpenMates/actions/runs/40014172598).
Only its two diagnostic helpers differ from source1b. Both retries retain
`actual_cli_exited_before_prompt` in an inline/base64 attachment; diagnostics work.
The backend, token/PIN wait, exit status and underlying cause remain unknown.
Cleanup verifies zero containers/volumes and removed private accounts; evidence
upload succeeds for twenty videos and two images. No benchmark metrics are reached.
A separately proven bounded PTY drain race is now fixed with 47 inert checks and
independent review; credential/storage/readback/cleanup safeguards remain intact.
This has not been established as the CI failure's cause or verified in product CI.

The integrated candidate `c6504bc4912c91971ae7e8b66cac0474e9eebab7` passes
preflight and an independent 598-file dirty/untracked blob-and-mode census. Its
essential CI request `a67c3f4c860a43308b92598bdc184f0d8538160311205c10d9972629f3d9192f`
is queued. The reviewed unit stage has 21 inert checks, source-scoped retries zero
and one 18-minute deadline with 60 seconds reserved, beneath the unchanged
20-minute runner and 60-minute job limits. Actual cold-build/unit/product fit is
unproven; timeout fails rather than omitting any required gate. All twelve product
gates and two recordings remain open. Separate requests queue the existing web
load/streaming-render measurements on the same pre-WASM source. These provide a
partial BEFORE baseline; broader controlled CPU, RAM and core-flow timing still
needs implementation and evidence.

The trusted essential-target backend selector is deployed as
`0dd1c1f78cd492d74af72afa6ca3f58a1c160e8e`, with ten focused tests. Candidate
coverage metadata requires the isolated committed-fixture AI worker. This supplies
protocol replay without provider credentials or inference/model overrides.
Web performance collectors and a read-only production asset inventory are also
integrated after review, with ten pure Node tests. The trusted production-build
attachment hook is deployed as `a439ae4dc822235f04b84e67083380b37011519f`, with
32 inert tests, independent review, verified source blobs and deployment gates
passing. It binds inventories to the actual served fresh/restored build, refuses
special files without blocking and rejects mismatched inventory bytes. Actual
production inventories and BEFORE measurements remain UNRUN; no WASM runtime is added.
Capture that baseline before browser work, which begins immediately after essential
native proof. Full CLI/app parity Task `083cfc56-4db3-43c2-85d4-325e2bb8b429` remains
required separately. The reviewed essential bindings and capability matrix are now
integrated in source: 59 capability rows and 156 declared language gaps. All four
binding security findings are addressed in source; 48 new shared outcomes and ten
internal tests remain uncompiled/unrun. The added reclamation regression observes
actual expired-stage removal, socket closure and admission release in the production
reaper path, with test-only barriers; its execution is still pending. The combined static API inventory now passes
with 1,555 Rust, 1,515 npm and 1,126 Python APIs, 156 explicit gaps and zero real
conformance executions. The retained 48/567 pass and its 147 gaps are
historical exact-source evidence, not a current all-three pass for these additions. Preview availability establishes no essential
completion, full parity, registry publication, global cutover or retirement acceptance.

Actual macOS testing remains required. The configured Mac is currently unreachable
and no online Mac is visible through Tailscale; Rust/toolchain and runtime readiness
are unverified. Use a coordinated Mac handoff or admitted typed remote capability
when available. No Apple implementation is started before web verification.

## Approved rollout amendment — 2026-10-23

The user's latest explicit decision supersedes the earlier complete-CLI-before-web
sequence. First prove essential authentication, encrypted chat, streaming/cancel,
persistence and sync/reconnect/recovery through the entirely Rust CLI/TUI. Then
begin browser/WASM integration immediately. Full CLI command/app parity remains
mandatory as separate work, with Task `083cfc56-4db3-43c2-85d4-325e2bb8b429`;
SDK-wide parity TASK-7993 and all release/security gates also remain required.
TASK-1233 owns essential native proof, TASK-9393 the essential shared core, and
TASK-9558 begins after that essential gate, not after exhaustive parity.

The new exact fingerprints and the latest user-authorized Plan-backed approval
are retained in the [sequencing approval record](essential-native-browser-sequencing-2026-10-23.json);
earlier approval hashes remain historical rather than authorizing this delta.

That essential gate is **open**: the installed source1b preview retains its live
chat/recovery defects. Reviewed current-source monitor, recovery and CLI activation
fixes are integrated, but remain uncompiled and without product proof; the TUI
recovery pump hook is pending. Local passing tests do not establish live
chat synchronization/recovery. Fix and verify these concrete essential defects
before browser admission; do not mistake unrelated app commands for blockers.

Expose a verified Rust executable alongside the installed npm CLI early for daily
testing through a separate command or installation path. Do not automatically
replace the global command. Keep the old command and code until full parity and
security are verified and both agent and user explicitly accept retirement.
The separate guarded installation above supplies the preview; this documentation
update performs no runtime operation and does not authorize retirement.

Capture web measurements **before** browser integration and repeat them afterward:
actual download/transfer, compressed JavaScript and WASM separately and combined,
WASM initialization and cold startup, usable chat and essential core flows, CPU
and RAM under matching conditions. Minimal overhead is not assumed. Keep the
original TypeScript native benchmark inputs and report renderer versus standalone
full-application results separately. Svelte owns UI/DOM and thin browser APIs;
shared Rust owns reusable operations/crypto/auth/persistence/sync/recovery.
Headless SDK credentials stay explicit, npm/Python remain direct libraries, and
cross-SDK/security/self-host GitHub CI requirements are unchanged. Web verification
precedes coordinated Apple migration; backend migration waits for all client
migrations and accepted cleanup.

Current bounded evidence is recorded in the preview/stage checkpoint above:
goal-chat passes 35 focused regressions and strict checks, while the SDK passes
316 tests including 14 host regressions. The source-host prerequisite remains
parked without FFI/all-three proof; essential sync/recovery remains open. The
clipboard yank is resolved with qualified audit results. Current CI fails later
at benchmark preparation, with successful retrieval, cleanup and evidence upload;
preceding diagnostic/retrieval failures retain their run-specific qualifications.
No performance, full-product, publication or retirement proof is inferred.

## Earlier captured evidence (source qualifications retained)

Current captured native source is `034a77d428aea2400950db8daa75c5dc56439da2`, tree `c050f66f6eff887349b92c7df059123c42bec5ee`, covering 546 paths. [Run 39986942686](https://github.com/glowingkitty/OpenMates/actions/runs/39986942686), request `0c801b4e82586bd3fe84be538eaa3b0111fab2c1f1075219823c9d05e08d75f7`, fails early at the attested Node producer's `source_mode` boundary, before candidate build, account setup or product checks. Exact mode, UID and path were not retained and remain unknown. Root attempted result retrieval once, which failed with “Expected one unexpired”; no artifacts or recording are available, evidence upload is impossible and cleanup is not established by retained evidence. Private bounded diagnostics and a fix are directed; no successful product or cleanup result is inferred. The [matching private ARM64 release build](native-source-authoring-release-2026-10-23.json) now passes with 181 source inputs and 145 runtime inputs held exactly before and after. Its independent owner-private `0700`, single-link pin is 24,191,320 bytes, SHA-256 `292873233819aa29901d5bb465ab58dbaa9ca1ea52cc989788a40b077748334f`. The cache-assisted build takes 265.06 seconds with minimum 34.2378 GiB free; it is not a clean-build benchmark. The binary is uninstalled and unpublished, and the build does not establish CI product proof. A fresh audit is assigned but remains pending.

The trusted Node producer corrections were deployed successfully as `3a910cf8ea60ea5c03f2c6d5a66d6c79c8451669` (six paths) and `2d6a3bb7be5571541f2ec302aa89d55cbd1fadc6` (fake-fixture chmod/umask test only). Canonical focused checks pass 36 Python and seven Node cases under umask `077`; that local evidence does not turn the later early CI failure into a pass. Source-host and goal drafts have no accepted applied or verified result yet; goal integration/compilation is in progress. No successful implementation or parity result is claimed. The actual 48/567 SDK and qualified 405-test native checkpoints below remain retained evidence, with 147 gaps and all rollout/platform/acceptance requirements open.

Preceding native CI source `cf53` covers 520 paths with exact preflight and an independent census of all dirty/untracked blobs passing. [Run 39971370205](https://github.com/glowingkitty/OpenMates/actions/runs/39971370205), request `81eeb41b422e6dd9f42e1687f9097aee17103e79e9dff93453f8265d34b87949`, fails both attempts at `file_boundary_nodeRuntime_mode` after all fifteen authenticated-terminal checks, pairing and the full Workflow-to-Project unlink proof pass. Native Cargo staging passes, but metrics are not reached. Cleanup is verified, root retrieved the receipt once, and evidence upload exits zero. The Node boundary establishes only a failing `mode & 022` check; the exact CI Node path and permission bits are not observed. A reviewed six-path Node-producer correction preserves the explicit launcher guard and raw supplier. Its private candidate was `92840d8c47e64b307a2a8002d68a4a982d146c8d` (base prefix `d92d`): the first deployment attempt `93ed` stopped on Ruff in a new test before commit. The corrected deployments above subsequently succeeded; the newer CI result remains the separate early `source_mode` failure.

Team Plan authoring has an existing API/protocol prerequisite, rather than a Rust-only wrapper regression. The [Plan route contract](../../../backend/core/api/app/routes/user_plans.py) exposes master/chat/Project wrapper creation without a Team create context, and writes resolve Personal scope. [Linked-Project admission](../../../backend/core/api/app/services/user_plan_service.py) is Personal; [Plan persistence and wrapper filtering](../../../backend/core/api/app/services/directus/user_plan_methods.py) require a master wrapper and filter wrappers by the requesting user, so another Team member cannot simply read the creator's wrapper. [Workspace moves](../../../backend/core/api/app/services/team_workspace_service.py) change owner/slug without establishing Team Plan wrappers; npm's Team-wrapper move behavior is Project-only. Existing npm/Python/web full Plan authoring is master-only too; partial Team-query reads are not a complete authoring contract. Native goal handling must therefore retain its Team refusal before inference, with no Personal fallback and no API-key attempt to unlock Team keys. Eventually this requires an agreed Team-role, wrapper, link, slug and cross-member-read contract followed by all-three-SDK vectors. Current Plan conformance is Personal; the Team vector in the Plans/Workflows fixture covers Workflows. This records the shared capability gap, not approval for a new backend implementation or Rust backend rewrite.

The [actual source-authoring combined gate](sdk-conformance-project-source-authoring-2026-10-23.json) now passes all 48 adapters and 567 results with 147 gaps and `releaseEligible=false`. Its [provenance](sdk-conformance-project-source-authoring-2026-10-23-inputs.json) binds aggregate `2b0a18bd4fd9c93fa28f716f5a29de651dd25b069801fc6dcc6892e3070600bc`, unchanged source/native artifacts and all three locks, with minimum 34.457 GiB free. The [handoff](sdk-conformance-project-source-authoring-2026-10-23-handoff.json) records fresh libraries from 218 inputs: Node SHA-256 `8704aade3dcdc161fc1f2ed6ba14d3f77b68796015656c6d7516d001e3920f1d` (44,856,280 bytes) and Python `de8c4131326f570ffc3dd0a9480e4818c47f488323a5fff7235c84535975b5b9` (51,549,096 bytes). All three SDKs pass the same 25 source-authoring vectors; the bounded facet remains partial and does not establish a live filesystem/terminal source host or API-key support. Historical 45/492 and earlier checkpoints remain source-qualified and unchanged.

The known generic workspace return-fence defect is fixed and reviewed on `ca05`/`82c7`. Actual coverage comprises eight test functions, including sixteen lifecycle races across all four work families and four actions, source-specific lifecycle cases, bounded admission, released Client access, registry/wipe checks and usability of a distinct replacement account. Strict Clippy and both binding features pass. This resolves that known critical defect; broader lifecycle/platform acceptance remains normal required work rather than an unverified claim about every client.

The first 48-adapter attempt failed because the older work-cancellation fixture expected `[]` instead of the security-correct typed `cancelled` error. All three runners now enforce that shared oracle and pass all ten work vectors; complete HTTP settlement, rotated credentials, queued/fresh callers, revision and network/write counts remain asserted. Exactly seven noncompiled post-build corrections are qualified in the handoff: three work runners, the work fixture, two Python 3.10 typing definitions and the gate oracle guard. Actual Python source25, four pure checks and two type-contract checks pass. A real local Python 3.10 interpreter is unavailable; the minimum-3.10 stdlib type check was added before the unchanged 3.12 publication setup but has not run in CI. No model, routing or default values changed.

The current native `--all-targets` unit run passes 405 tests with zero failures and four product cases ignored. The retained summary `/tmp/d1c4-native-current-full-unit-2026-10-23-summary.json` explicitly notes that the driver fenced SDK/library inputs, but did not snapshot every native source at command start. Supplemental comparison against the prior native compiler checkpoint and final owned-source corrections passes; no stronger start/end native source fence is claimed. Workflow ask passes 51 focused tests including thirteen new cases and strict Clippy, while remaining partial. The catalog records 722 patterns and 580 flags: 442 partial, 278 unsupported and two implemented status rows; those counts do not establish complete parity. The private SDK host-session contract is not implemented. Native remote access, macOS verification, side-by-side dev adoption, SDK publication, source retirement and browser integration after essential proof remain open; Apple and backend work retain their approved later sequence. The bounded capacity watcher finished cleanly in under an hour after two admitted cleanup operations covering 34 freshly unused images and unused cache, with last available capacity about 35.19 GiB and no daemon left running.

Preceding captured candidate `ff71d1125903b2920bb554c3c6d5f175f0173267` has tree `2dbb2c2d673838979d0f69b646870d2ed616aff6`, base `25dfaf520724c693dac4d743abb20064f41c9d49` and patch SHA-256 `7eb8b1cba6a34e1cc6cfa7f6e21a1fc23bb31f01fc35162593c34a300bb9b7e1`. Its 516-path preflight and independent coverage of every dirty/untracked blob pass. [Native CI](https://github.com/glowingkitty/OpenMates/actions/runs/39963780052), request `e24323c52621dad1f1624d9e9a4c8c55691e53788f863e10087fd47a974047cc`, failed both attempts at `native-workflow-project-removal.ts:24`: the helper expected root-level `project_id`, while the successful CLI response is `{project:{project_id}}`. All fifteen authenticated-terminal checks and browser pairing passed before this failure. Application preparation, the file-boundary checkpoint and metrics were not reached on this run. Cleanup is verified, root retrieved the exact receipt once, and evidence upload exits zero. Meaningful source-helper regressions and the missing backend Project-delete `confirmation_project_id` cleanup acknowledgement are being corrected by their owner. New exact-source CI remains pending; the earlier staging-v2 40-test/review checkpoint is still not verified through the full application flow. The matching private ARM64 build passes with 176 exact runtime inputs and all 143 actual dependency files covered: 24,125,784 bytes, SHA-256 `9d07d0690b049587d59c71fb77633a15d3347df356fa5abb35c75ef934751d97`. Its cache-assisted build takes 265.07 seconds with minimum 35.7828 GiB free; this is not a cold-build performance claim. It remains uninstalled, and older pinned binaries are retained. Later host-only facade/harness fixes are outside this capture; its Rust compiler inputs and artifact remain unchanged.

The retained application source is `2bc00c0971dba8ede7f09dd717e5cd2a6b3c2a2e` (tree `6e9e8a30b2773042d597b6d73fe79a30983c2a14`, base `25dfaf520724c693dac4d743abb20064f41c9d49`, patch SHA-256 `2278a6ff9de976b24dd9f1e9acbe23fb87ee211760e5acc550870c171993f0cd`). Its 486-path capture preflight and independent changed/untracked-input census pass. [Self-host CI](https://github.com/glowingkitty/OpenMates/actions/runs/39943002622), request `c80d15bc3544faf543519316f7c48e476cf20664e7f643b50b6a0aebd22b9bfe`, succeeds: sixteen steps, four browser flows including admin, passkey and recovery, and verified cleanup. Evidence upload exits zero; all four videos are unavailable and seven images uploaded. This success applies to 2bc, not subsequent working-tree changes.

The [original native proof](https://github.com/glowingkitty/OpenMates/actions/runs/39942997249), request `189e20000b41ae9101f468fe61c03329e4bf2b9a6042e1227632be094c98b24e`, failed `compose_context` on both attempts after all fifteen authenticated-terminal checks and browser pairing passed. The narrow trusted-harness fix was deployed as `2afdd899c246d98e51c26300f483fa1cdedb2681` with six focused tests passing. Its [rerun](https://github.com/glowingkitty/OpenMates/actions/runs/39952896478), request `c437f06faef7abf53631796c70988998916f3f836baaa3b95ba502ec31a5a5ae`, passed the same auth/pair boundaries on both attempts, then failed `file_boundary`. Cleanup is verified and the uploader exits zero. Producer/source diagnosis finds Cargo release output has link count two; the failed CI inode itself was not observed. A five-path staging-v2 correction uses private `/tmp` staging outside uploads, descriptor-anchored copying and cleanup. Forty focused tests and independent review pass; the later ff71 CI above stopped at the earlier Workflow helper assertion and did not reach staging-v2 application preparation.

The matching private 2bc ARM64 build succeeds at 24,125,784 bytes, SHA-256 `9db62176a53d6afe414cd01b7f5414e37014fdbf66605ea4b037933da5465f75`, with 167 runtime inputs checked. It is uninstalled. The current watch, Workflow and staging corrections below are outside that captured source and binary. Root remains sole CI coordinator; no current complete native proof, signed-in performance result or installation acceptance is claimed.

Retained whole-application checkpoint, 23 October: [376 native tests (324 library plus 52 other)](native-local-checks-2026-10-23.json) and 267 SDK library tests pass. Four product tests remain ignored locally. These whole suites precede the root's mechanical `privacy.rs` Clippy let-chain edit. Final source aggregate `b74c10bff376036418313a6c57e5c4f4cf9453548ed7282f73f5cb201a9693b6` then passes seven focused privacy tests, SDK/native strict all-target Clippy and the package input guard with 207 inputs held. Whole suites were not repeated after that mechanical edit; the earlier aggregate driver's Clippy failure is retained rather than represented as an uninterrupted passing run.

The [actual combined privacy gate](sdk-conformance-privacy-2026-10-23.json) now passes 42 adapters and 417 vector results, including all 39 local privacy cases through each of the three actual libraries. Fresh locked/offline NAPI/PyO3 artifacts, source inputs and all three lockfiles held throughout the run; the [raw provenance](sdk-conformance-privacy-2026-10-23-inputs.json) records a minimum 32.512 GiB free. The [sanitized build handoff](sdk-conformance-privacy-2026-10-23-build-handoff.json) retains toolchain, artifact identities and source/lock fences without copying build environment values. The historical [39-adapter/300-result checkpoint](sdk-conformance-task-order-2026-10-22.json) remains unchanged. All 141 broader SDK gaps remain open and release is blocked.

After that successful gate, root corrected 17 contract-test annotations in seven files, with exact before/after hashes in the [comment-only correction receipt](sdk-conformance-privacy-2026-10-23-post-gate-metadata.json); runtime logic and fixtures did not change. A subsequent explicit-credential constructor-policy fix is review-clear and passes 50 npm tests, 136 Python tests, Ruff and ESLint. Strict TypeScript checking still reports three errors also present in the original base and canonical dev: missing `DecryptedMemoryEntry` fields in `projectFileExecutor` and two `BufferSource` mismatches in `projectIgnoredReadGrant`. Those unchanged errors are outside the eight-file fix; no complete TypeScript pass or unrelated repair is claimed.

The [final explicit-credential gate](sdk-conformance-privacy-explicit-2026-10-23.json) now passes all 42 adapters and 417 results with 141 gaps and `releaseEligible=false`. Its [raw provenance](sdk-conformance-privacy-explicit-2026-10-23-inputs.json) records unchanged exact source, matching fresh native artifacts and all three lockfiles, with minimum 37.587 GiB free. The [sanitized handoff](sdk-conformance-privacy-explicit-2026-10-23-handoff.json) records the fresh binding build, the 186 host credential cases (50 npm and 136 Python) and the qualified three baseline TypeScript errors. The earlier 417 pass remains unchanged, rather than relabeled as this later source.

The earlier disk-reserve interruption was not an assertion failure. Following explicit user approval, root removed all 68 specified unused untagged images through admitted operation `docker-74760684`, increasing available capacity from approximately 25.2 to 39.5 GiB. Container identities and their images stayed unchanged; tagged images, volumes, source and evidence were retained. Only sanitized counts, hashes and invariant outcomes are retained in the handoff; no container or other image identifiers are published. The coordinator revalidated and removed 35 further unused untagged images, preserving container identities; immediate capacity gain was approximately 0.02 GiB. An admitted prune of unused Docker builder cache then exited zero, increasing available capacity from 30.6 to 36.856 GiB with containers and images unchanged. Only sanitized outcomes are recorded here, without private image/container identifiers or engine output. The user authorizes ongoing safe cache cleanup without routine confirmation. Source, evidence, active runtimes and recovery data remain protected.

Project Task watch is now applied in the current working tree. The SDK library passes 289 tests, the focused watch set passes 35 plus the stronger pre-await regression, and strict Clippy passes. Native focused coverage passes 36 tests and Clippy; the binding actor passes nine tests and Clippy on the `6b19` checkpoint. Actual Rust public watch conformance passes all 25 cases against fixture SHA-256 `183537898ecbade06b5dad7087b269e33e47edcc8c347ee9aa27fa9bd84a07c2`. Fresh NAPI/PyO3 libraries now hold 204 inputs and all three locks, with minimum 36.67 GiB free. Their hashes are Node `7b113370f41597fbf45dbbf591e684e618a4d4c8a69a46f3f32e35c34e453618` and Python `0dcdba902f4edfd15868a710a0342dbfe700864c71a1f32a7a9a98502200632f`. The [complete watch conformance gate](sdk-conformance-project-task-watch-2026-10-23.json) now passes all 45 adapters and 492 results, including the same 25 watch vectors through Rust, npm and Python. The [recorded source and artifact provenance](sdk-conformance-project-task-watch-2026-10-23-inputs.json) binds source aggregate `57ac1347e740485cdac1559662b7bc9c9e23faa051f3b864ed10a52426d96836`, unchanged native artifacts and all three locks, with minimum 34.314 GiB free. The [handoff](sdk-conformance-project-task-watch-2026-10-23-handoff.json) qualifies two post-build noncompiled corrections: the npm parameter-property parse refusal and Python's missing explicit private-operation flag. Six Python cleanup mocks and direct TypeScript lint pass. Earlier interrupted attempts include a capacity-guard stop below 30.75 GiB with source held and no assertion failure; none is relabeled as this successful source-fenced run. Additional admitted cleanup pruned about 3.35 GiB of unused builder cache, then removed 18 revalidated unused untagged images while preserving container/image mappings; available capacity rose from 29.149 to 35.666 GiB. Safe pnpm-store pruning removed cached metadata, 4,118 files and four packages. No editor-server or user-data cleanup occurred. Public claims remain narrower than the separate internal queue-pressure, pre-await and serializer-join regressions. That watch checkpoint keeps the facet partial, adds three qualifications for 144 gaps, and blocks release; its source inventory records Rust 1,373, npm 1,474 and Python 1,083, with 53 gate and three inventory static tests passing. The subsequent source-authoring registration above increases the current gap count to 147. The facet remains partial despite the actual 45/492 pass; no complete SDK or command capability is claimed. Historical 42/417/141 evidence remains unchanged.

Workflow removal from a Project passes twelve focused tests and strict all-target Clippy, and the later cf53 run above passes its full unlink proof; Project addition and YAML parity remain open. The preceding catalog recorded 722 patterns, 580 flags, 441 partial handlers and 279 unsupported patterns; the current counts are recorded above. Full native CLI/TUI parity, current product verification, dev switch, registry publication and user acceptance remain open. The 2026-10-23 sequencing amendment above supersedes the earlier full-CLI/dev-replacement browser prerequisite; full parity and backend boundaries remain required.

Captured source `48d2a2de82dfcda95586106c9090f5e2974d9ccb` passed capture preflight across 464 changed paths, but both [native application CI](https://github.com/glowingkitty/OpenMates/actions/runs/39925282376) and [self-host CI](https://github.com/glowingkitty/OpenMates/actions/runs/39925355788) failed. Native attempt zero passed protocol/authenticated terminal and browser pairing, encrypted-vault restart, wrong-PIN and cancellation checks. It then refused the canonical CI app port 5173 because the preparation guard required 3000; signed-in measurements were not reached. Retry reached an acknowledgement conflict after authorization succeeded and authorizer polling reported binding-required. Source analysis identifies stale incoming Cookie binding versus the authenticated effective successor; no secret/token lineage was logged. Both endpoint guards and effective-credential binding have working-tree corrections with focused tests/review; new exact-source CI remains pending.

Self-host source and image install/start/update lifecycles, browser update ordering, passkey and recovery checks passed on 48d2. Native `server make-admin` then returned generic subprocess failure. Source uses the nonexistent `users` SQL relation instead of canonical `directus_users`; retained stderr does not independently prove that diagnostic. All three references are corrected in the working tree with focused regressions and review. The [retained self-host audit](selfhost-ci-2026-10-22.json) preserves earlier failures and the later lifecycle passes; complete self-host acceptance still requires new CI. Cleanup was verified for both 48d2 runs.

The matching private 48d2 ARM64 candidate remains pinned at 24,125,784 bytes, SHA-256 `ce0bd23350fb02f68515bcf94171d944aa7b7c7ec64bced52ef7335370978179`, with 163 runtime inputs held before/after compilation and pinning. Cargo's inherited group-writable output caused the first copy guard to stop before copying; owner-private mode, stable identity, independent hashes and ELF checks then passed without recompilation. The empty copy is retained. This binary remains uninstalled and excludes subsequent command, journal, privacy and CI corrections. No current product, installation or performance acceptance is claimed.

The following earlier checkpoints retain their original source and scope.

The CLI, SDK, sync and storage Specifications,
readable examples, architecture docs, canonical agent guidance and durable Plan
record the approved shared Rust architecture. Their exact-hash approval checks
pass. The [SDK checkpoint](task-order-local-checks-2026-10-22.json) passes 274 tests;
the preceding [native checkpoint](redis-probe-local-checks-2026-10-22.json) passes
342 tests and strict all-target Clippy. Source hashes held throughout both.
Four product tests remain intentionally unexecuted locally and require isolated
GitHub CI.

Fresh RustSec data rejected existing Tokio 1.54.0 for a timer memory-safety
race. All three Rust packages now pin 1.54.1. The [dependency audit](dependency-audit.json)
passes all three exact lockfiles with zero known vulnerabilities, unsound or
yanked warnings; three native maintenance notices remain visible. Earlier
binaries, including `2d94b407`, cannot authorize installation or publication.

The `2d94b407` native CI run passed its complete protocol smoke on attempt zero,
including draft clearing, rename/search and empty Project-item operations. It
then failed a harness assertion that searched raw ANSI fragments even though
the completed terminal screen showed a successful login. Retry hit a fixed
workflow slug retained by the first attempt's soft-deleted fixture. Completed-grid
assertions and fresh explicit fixture slugs now pass focused regressions and
review. The overall native run failed; its latest terminal recording is uploaded,
disposable resources cleaned up, and later vault/pairing/benchmark stages remain
unverified. The matching self-host run passes source lifecycle and image
install/start/dry-run, then fails the worker-queue probe's Redis CLI transport.
Earlier database/cache/Vault checks pass. Its subprocess cause remains unresolved;
unsupported `--json` is a hypothesis, with no CLI-version or stderr evidence.
Cleanup is verified; no attempt recording was returned for this self-host run.
The CSV compatibility correction passes focused tests and refreshed independent
review. An intermediate AUTH/SELECT batching issue could let rejected database
selection precede a mutation against DB0; that source is excluded. Rust now waits
for each validated acknowledgement on the same connection before sending another
command. Actual probe construction drives synthetic child journals proving no
mutation follows bad/missing setup replies, plus successful DB2 and cancelled-child
cleanup cases. The full 342-test native suite, strict all-target Clippy and package
guard pass with unchanged source. Actual self-host CI is still required and the
historical subprocess cause remains unproved.

Task presentation now shares explicit-locale Rust ICU ordering with direct npm
and Python functions. All three actual libraries pass the same 22 vectors
(66 results); focused core/native/host tests, strict Clippy and independent
review pass. CLI JSON/list/status retain wire order and TUI refresh retains the
selected Task ID. Unicode parity is qualified to recorded fixtures and data
versions; macOS locale preferences and binary/WASM size remain unmeasured.
The [whole combined gate](sdk-conformance-task-order-2026-10-22.json) passes
39 adapters and 300 vector results with held source and artifacts. All 141
broader SDK gaps still block release. A first environment attempt failed at
Python import because system Python lacked `toon_format`; the passing run used
the retained SDK venv. That does not explain the older blank-stderr child failure.

Signed-in CLI and TUI measurements are integrated after independently paired
history readback. The CLI meter has 33 mocked tests; the TUI helper has 52, the
canonical real-line history fixture has ten, and integration has fifteen.
Static checks and independent reviews pass. Five alternating pairs measure each
CLI flow and the TUI workload, using actual child CPU/RSS and complete visible
checkpoints. Uncertain Task cleanup retains private rotating profiles and an
atomic recovery journal for the runner lifetime. Actual signed-in measurements
and masked TUI video remain open. No registry publication, macOS verification,
dev CLI replacement or npm retirement acceptance is claimed.

Patched source `da67ee7ad3be48c0faa980f53d3085fa312ddd5f` passes capture
preflight across 456 changed paths. Its
[native terminal/application CI](https://github.com/glowingkitty/OpenMates/actions/runs/39871349634)
failed after passing protocol smoke and all fourteen authenticated terminal checks,
including encrypted vault restart, account isolation, logout and terminal
restoration. Browser-assisted pairing then exited one with a conflict at its
acknowledgement request after the new-vault passphrase prompt. The recorded child
exit is correct; the backend relay state causing rejection is not retained.
Browser context also reports a current-session verification error, with no proven
causal ordering. Further secret-free isolated-CI diagnostics are needed before
changing acknowledgement behavior. Retry hit a separate
fixed-title Workflow slug in the Python authenticated terminal fixture. That
fixture now supplies fresh explicit UUID4 slugs; eleven pure tests, Ruff and
independent review pass without changing lifecycle or privacy assertions.
The correction is outside the captured source, and signed-in benchmarks were
not reached. Exact-source artifacts are retrieved and cleanup verified. The
returned evidence upload command initially failed while the configured
local `api` container was absent. After the route recovered, recordings uploaded
successfully without rerunning tests. An initial Task activity write failed with HTTP 502. After sync
recovered, TASK-1233 acknowledged the new pairing-acknowledgement finding at
23:53:19 UTC; no pending write was resubmitted.
[Source/image self-host CI](https://github.com/glowingkitty/OpenMates/actions/runs/39871354094)
completed source lifecycle and image install/start/update successfully, including
the CSV acknowledgement-gated runtime checks and precise update status assertions.
The overall run failed on two later browser compatibility checks: the native
dry-run nested a field that belongs at top level, and installation synthesized
an API URL override that should remain optional. Passkey and recovery cases pass;
cleanup is verified. Both producer corrections now have focused regressions and
independent review, with browser assertions unchanged. Their new source requires
verification. Returned screenshots uploaded, but no video attachment was captured
for the self-host attempts. The [retained self-host audit](selfhost-ci-2026-10-22.json)
preserves earlier failures and the new exact-source lifecycle result.
Its private ARM64 release is pinned at 24,125,784 bytes, SHA-256
`cd602a84aee7fd4bc46cab9c0c5ddeb404afed0d4b6839bbf352a690037da212`,
with 162 exact runtime inputs checked before/after compilation and pinning.
It remains uninstalled. Compilation resumed from a disk-guard stop after owned
compiler-cache cleanup. A corrected copy guard excludes read-access time while
checking stable identity and independent full-file hashes; the retained copy was
validated without recompiling. This is not a cold build-time measurement or
successful product acceptance. Plan outcome bookkeeping after capture does not
alter the runtime inputs verified against that source. The new CLI and installer
changes below are outside that binary and require a new build.

Implementation continues on 23 October. Personal `drafts clear` now uses the
existing shared Rust operation with legacy unconditional JSON, receipt-gated
success, credential rotation and cancellation fences. Five focused cases cover
invalid/auth/scope admission, saved history versus draft-only shells, delayed or
foreign acknowledgements and uncertain mutations. The catalog remains explicitly
incomplete; its current maintained command mappings and remaining refusals are
recorded in `config/cli-command-catalog.json` (pending Rust source publication). Full native validation now passes; actual-CLI fixture
proof remains in progress. Pairing diagnostics now pass sixteen backend mock tests,
seven helper/PTY cases and focused static checks. Only closed stage/status/error
categories are retained, with bounded buffering and a bounded post-error state
read; this does not prove atomic backend state at rejection. A new isolated run
must identify the cause before changing acknowledgement behavior. No SDK,
client migration or dev installation completion is claimed.

The application is implemented entirely in Rust. Ratatui/Crossterm own the
terminal and layouts; Tokio, reqwest and tokio-tungstenite own the event loop and
protocols. Rust implements authentication, OPAQUE pairing, encryption, privacy,
encrypted storage and recovery. The executable does not load a JavaScript
runtime, spawn a TypeScript client or exchange rendering/state messages with a
sidecar. The separate TypeScript adapter exists only to measure the existing TUI.

Implementation: `frontend/packages/openmates-tui-native` (pending Rust source publication).
The installed TypeScript CLI has not been replaced. Previous hybrid code and
measurements are superseded and excluded from this comparison.

The user-approved scope now includes the **complete CLI migration** and three
synchronized headless library SDKs. The [Plan](plan.yml), existing CLI/SDK/TUI
Specifications and [architecture](../../architecture/platforms/cli-package.md)
record that decision. The Rust client core is extracted to
`packages/openmates-rust`; command parsing, rendering and interactive profiles
remain in the application. SDKs must never inherit CLI login state automatically
or implement operations by launching a CLI.

The maintained command catalog records native mappings and remaining gaps;
recognizing the hierarchy alone is not implementation parity. Complete native handlers,
three-language capability equivalence, platform resolution, isolated self-host
setup CI, full-application comparison and dev installed-CLI replacement remain
required work. Shared crypto/protocol conformance and release gates are implemented, and
declared capability gaps block publication. The original npm CLI/TUI remains
operational and its source cannot be retired until passing parity/security
evidence **and explicit agent plus user acceptance**. No replacement acceptance
or migration completion is claimed here.

## Behavior and adoption

| Area | Native implementation | Verification boundary |
|---|---|---|
| Presentation | Six workspaces, chat/sidebar, Tasks board, Project files, Workflow graph, settings shell, rich Markdown, links, saved embeds, questions, sharing and downloads | Native rendering/controller tests; real-terminal CI pending |
| Input | Grapheme editing, multiline bracketed paste, isolated per-chat drafts/retry, pointer hit maps, resize, terminal selection and masked forms | Native Unicode/controller tests; no-Node PTY and signals CI pending |
| Sign-in | Password v2 and legacy unwrap, TOTP, OPAQUE pairing, origin-bound credentials | Independent/shared crypto vectors; 48d2 attempt zero passes authenticated terminal and browser pairing boundaries; retry binding correction needs new CI |
| Local state | OS keyring, owner-only local-key fallback or explicit encrypted vault, atomic publication, account/session/context-bound encrypted credential/chat caches and process locking; separate owner-private plaintext Task hook cache | Storage failure, tamper, owner, permission, cancellation and logout tests; actual desktop keyring not exercised. The Task cache is a local filesystem foundation, not verified foreground networking. |
| Chat protocols | Phased metadata sync, canonical paginated history, encrypted admission/recovery persistence, PII detection/restoration, explicit memory consent, Project context | Native protocol boundary tests; real AI continuation/recovery evidence still required |
| Team context | Fresh scoped keys, Team-only send context, preview consent, direct-chat group-key rejection and revocation monitoring | Native scope/preview/monitor tests; isolated multi-account server evidence still required |
| Mutations | Tasks/Projects/Workflows, supported settings, explicit share metadata, safe chat/Project export | Native unit tests; isolated CRUD smoke pending |
| Apps | Native metadata, confirmed schema-driven skill execution and encrypted saved results | Six mocked protocol cases and focused typed-form/controller tests; product execution not yet verified |

The explicit application-owned Project Task hook cache is an exception to encrypted
local cache storage. Its `snapshot.json` and derived `tasks.txt` contain plaintext
Task titles, bounded descriptions/activity summaries and ownership metadata for
local Codex readers, protected by owner-only `0700` directories and `0600` files.
They are separate from the credential vault and are not encrypted by enabling that
vault. Atomic snapshot publication, writer locks, reconnecting/revoked markers and
recovery fences protect consistency and scope; they do not establish secure disk
erasure or protection from the owning user, backups or privileged processes. The
headless SDK reducer owns no files, and this cache does not launch adapters or
implement the foreground remote-access network lifecycle.

This is an opt-in native implementation. Secondary chat Plan/Tasks/Files/Usage
panels, upcoming-event shelves, some advanced settings are not yet at full feature parity.
Direct-chat identity recovery needs a network connection after restart. Project
execution jobs, countdown approvals, connected-account consent and direct sandbox
Apps streaming also remain restricted. Browser verification remains
explicit for settings operations that require it. Enhanced semantic privacy
currently blocks sending when enabled; it never silently falls back to weaker
detection or launches a TypeScript privacy daemon. Filesystem hardening is Unix
only. These restrictions must remain visible when assessing replacement readiness.

## Security and stability

The [security inventory](security.md) maps existing controls to Rust code and
evidence. The [dependency audit](dependency-audit.json) records the exact lockfile,
RustSec database and unsuppressed findings. It found no matching published
vulnerabilities, unsound or yanked packages; three keyring/D-Bus maintenance
notices remain. This is not an independent cryptographic audit or proof of complete
security equivalence.

The runtime separates UI drawing from network and keyring work, bounds ordinary
queues and protocol bodies, preserves critical logout delivery, and discards
responses from older owners/views. Session/Team revocation clears private UI
content before credential cleanup. Terminal guards and signal handling restore
raw mode, mouse capture and the alternate screen. Cancellation cannot let a
started storage save overtake logout. Pairing saves credentials before relay
acknowledgement and rolls back a cancelled newly admitted session.

The encrypted-vault wrapping key is cached only after successful authentication,
bound to the record/context and protected by a constant-time passphrase verifier.
This avoids repeating a 64 MiB Argon2 derivation on each request. Wrong passwords,
changed metadata, expiry and logout still invalidate access; tests observe key
erasure on invalidation and drop.

## Performance methodology

[`benchmark.json`](benchmark.json) holds the final results: five independent
processes per case, 36 backend/workload combinations and 20 warm samples per phase.
The complete native source hashes remained identical before build, at measurement
start and after completion. Both Tasks renderers used identical selection targets.
The driver gives each renderer the same raw synthetic Markdown and Tasks, with
20/100/500 items at 80×24, 160×50 and 240×70. Each implementation independently
lays out and paints its own UI. Five separate processes per case report cold
layout/ANSI, warm draft and scroll median/p95, CPU, peak RSS, startup and ANSI
bytes. The TypeScript baseline is prebundled from unchanged source using the
existing esbuild installation; source-loader/transpilation time is excluded.

These are offline renderer/process measurements. The designs generate different
cells and ANSI; output is retained to make that difference inspectable. Rust's
benchmark executable can discard unused networking/crypto through LTO, while the
TypeScript renderer imports its existing module graph. RSS is therefore not a
measurement of both complete signed-in applications. Network, account unlock,
model/provider latency and actual terminal paint latency are outside these numbers.

## Measured results

Median milliseconds, on the same Linux ARM64 host:

| Workload | Rust draft redraw | TypeScript draft redraw | Rust movement | TypeScript movement |
|---|---:|---:|---:|---:|
| Chat, 100 messages, 160×50 | 0.471 | 9.451 | 0.605 | 13.181 |
| Chat, 500 messages, 240×70 | 0.764 | 12.649 | 0.981 | 18.237 |
| Tasks, 100 items, 160×50 | 0.616 | 40.733 | 0.619 | 67.025 |
| Tasks, 500 items, 240×70 | 1.128 | 67.857 | 1.132 | 114.799 |

Chat movement is history scrolling. Tasks movement follows the same selected
card through the board and its viewport. At 500 messages/240×70, chat draft p95
was 0.808 ms Rust versus 16.600 ms TypeScript; movement p95 was 1.025 versus
22.085 ms. Reported p95 summaries are the median of the five per-process p95s,
each calculated from 20 warm iterations; raw samples are retained.

The benchmark processes peaked at 3.1–7.9 MiB RSS for Rust and 102.2–147.0 MiB
for TypeScript. These are the renderer-process graphs described above, not full
signed-in application memory. In-process fixture initialization ranged from
1.164–26.605 ms versus 229.134–328.047 ms with the precompiled TypeScript baseline.
Rust did not win every measurement: cold chat layout at 500 messages/80×24 was
22.482 ms versus 21.719 ms. An unchanged Rust frame also emits 19/27 cursor/style
bytes while the TypeScript painter emits zero. The report preserves these costs.

Reproduce from the repository root with the Rust toolchain and Node on PATH:

```sh
node frontend/packages/openmates-tui-native/scripts/prepare-typescript-baseline.mjs /tmp/openmates-baseline
python3 frontend/packages/openmates-tui-native/scripts/benchmark.py --typescript-source /tmp/openmates-baseline --output /tmp/benchmark.json
```

## Complete CLI process measurements

[application-benchmark.json](application-benchmark.json) records five alternating
process samples per command on the Linux ARM64 dev host. It uses the complete
release Rust executable and the retained original TypeScript CLI at
`25dfaf520724c693dac4d743abb20064f41c9d49`, with Node 24.20.0. Both receive a fresh
isolated HOME. The baseline's supported latest-version override is pinned to its
hash-verified package version in both environments, excluding registry lookups
and background update checks. No account, API workload or inference is involved.

| Command | Rust wall median | TypeScript wall median | Rust peak RSS median | TypeScript peak RSS median |
|---|---:|---:|---:|---:|
| `--help` | 30.0 ms | 454.7 ms | 14.0 MiB | 124.3 MiB |
| `--version` | 29.9 ms | 470.1 ms | 14.1 MiB | 124.5 MiB |

CPU and peak RSS come from a small compiled measurement harness that starts
before forking the actual application, avoiding an inherited Python heap/RSS
floor. Its source, executable, compiler and command hashes are recorded. Wall
time includes the same meter launch/fork/wait overhead for both applications;
application CPU/RSS excludes the meter parent. An earlier diagnostic with an
identical 158,156 KiB inherited RSS floor was discarded and is not these results.

These results measure complete CLI process startup, separately from the renderer
measurements above. Help/version output and available functionality differ; the
numbers establish neither feature completeness nor signed-in TUI performance.
Interactive startup, idle CPU, input timing and terminal restoration remain
isolated GitHub CI measurements. Authenticated network/model latency is outside
this offline comparison. Raw samples, coarse five-sample p95s, output hashes,
source hashes and limitations are retained in the report.

## Verification receipts

The original native milestone passed 123 deterministic tests, and the first
CLI/SDK extraction candidate passed 160; both are historical checkpoints. The
next local checkpoint passes 222 native application tests (including nine admin
bootstrap tests) and 146 separate headless SDK tests, with strict all-target
Clippy. The two native product tests remain ignored locally and require isolated
CI. Rust formatting, SDK boundary audits and repository lint also pass. Shared library conformance executes
the Rust, npm and Python implementations; declared capability and platform gaps
block publication. Packed npm and Python library checks load their native
extensions with `PATH=/nonexistent`. These checks do not establish full SDK parity.
Authenticated protocol and real-inference probes are selected separately.
Isolated native product/terminal CI is
failed from candidate `c7aca884fba5ff55b3b952dc6b1c1a4055ea030b`, request
`c335a2abef4c7841cdd8d56098f18ac29703f82e95257cb1d7fc6afdf347e2f7`,
[GitHub run 39588844469](https://github.com/glowingkitty/OpenMates/actions/runs/39588844469).
Native password login received a forbidden response before PTY capture: the SDK
derived the loopback API origin instead of the existing localhost:5173 application
origin. The origin mapping and explicit app-origin option are corrected with unit
coverage; a passing exact-source CI rerun is still required. The incidental blank
browser recording is not native terminal proof.
The terminal recorder's native ANSI-diff support passed 64 focused parser tests.
No queued or superseded hybrid CI result counts as native application verification.

The expanded migration snapshot `3c00724bcda4dfdc322d2119a35bca9d6d0fad99`
failed isolated GitHub verification: native terminal/CLI request
`9d568f3400bdd80fc6176f648ce98f07048f2d026c1ab0da2bdf984de8c112a3`
(run 39603463206) and native source/image self-host request
`66ff1576911f9299dcb9edc1674c049e3aa95d9db0a2e482d5a4c8687f8a86b7`
(run 39603468852). The bare PTY did not answer Ratatui's cursor-position query;
terminal cleanup therefore completed before the raw-mode assertion. A bounded,
fragment-aware terminal-query responder now handles all three bare-PTY harnesses,
with byte-level regression coverage and unchanged product assertions/deadlines.
The self-host run failed while building the retained TypeScript baseline's web
Docker image, before native source/image installation. V8 exhausted its heap
during precompression; CI now forwards its existing precompression-disable switch
through Compose and Docker while preserving the production default. Both fixes
still require exact-source CI reruns. No native terminal recording or completed
full-application benchmark was produced by these failed runs. The incidental
browser recordings do not establish native terminal behavior; self-host setup
failed before a test-attempt recording was available.

The [shared conformance checkpoint](sdk-conformance.json) passed 24 actual-library
adapters, including positive authentication, bounded recovery and encrypted
Project creation. Its 123 declared language/capability gaps prevent publication.
The source inventory continues to advance after that frozen checkpoint; these
results do not claim coverage of later ports. Native server quick tests require
explicit credit confirmation, preserve a completed update receipt if testing
fails, and allow bounded cleanup on cancellation. Foreground continuous updates
stream separate iteration receipts and honor UTC windows; host transactions
retain their lock through a safe completion rather than being abandoned on a
terminal signal. Paid quick tests have not been executed as product evidence.

The complete-source snapshot `691c61548a5c400897ee2c426a57d3182010fe66`
compiled successfully in both GitHub runs. Native run 39616043435 passed the
bare-terminal rendering/input/signal checks and recorded the real terminal,
then failed in the original TypeScript arm of the interactive benchmark before
authentication ran. An input that produces no visible change cannot require a
new frame from the original renderer, which suppresses identical frames. The
harness now establishes a visible draft before cancellation, retains the same
frame deadline, and records failure phase and partial measurements. Authentication
now precedes measurements. Temporary baseline dependencies are removed before
artifact upload; the failed run's recordings, reports and baseline manifests
were recovered within the existing extraction limits by excluding those
reproducible dependency copies, with that selection recorded in its receipt.

Self-host run 39616049643 passed the retained TypeScript source setup, then
rejected `/tmp` as an owned installation directory before native cloning. Native
source installation now creates and validates the private target and clones
from it; three focused regressions cover the shared parent, argument boundaries
and unsafe targets. Source and image lifecycles still require a passing rerun.

The later local application checkpoint passes 267 tests across all targets,
with its two product tests ignored locally. Nine final RuntimeStore regressions
also pass, including the cancelled-admission/logout orderings. The native
bootstrap's ten tests verify rollback of an exclusively created profile, including
safe handling of the retained revocation files. Explicit API-key device/journal
state stays independent of cookie-profile revocation. These are local unit
checkpoints, not evidence of complete CLI/SDK parity or successful dev installation.

### Native CI workspace-loading checkpoint (2026-10-21)

Exact source `0b1f2e92bf7de99479c0c783862772982a2f7be8`, GitHub run `39624194048`, passed native password login and session validation, then failed a workspace list with `Offline`. Bare-terminal signal restoration and the recorded Zutty lifecycle checks passed before the protocol failure; authenticated TUI and paired application measurements were not reached. The failed receipt was restored and its evidence upload invoked. Source review found that Rust conflated foreground delivery capability with human interaction, while the original active CLI socket announces foreground true and interactive false. A bounded lifecycle correction and stage-specific protocol diagnostics are being verified; this is not a successful sync or cutover claim.

Self-host run `39624200032` on the same `0b1f2e92bf7d` source passed exact Rust compilation, the retained TypeScript source baseline, and native source install/start/health/status/update-plan/stop. Native uninstall returned `local_io_failed` after stopping the deployment; image mode was not reached. Retained diagnostics and cleanup were restored. Native source and image setup acceptance therefore remains open.

Catalog audit found five help-prose sentences mistakenly represented as commands; those rows were excluded with retained source references. Real dispatcher aliases and delegated chat-scoped Task/Plan routes still need a full audit, and two Plan Task add/remove help rows are stale in the original dispatcher. Catalog counts therefore do not establish feature completeness.

Latest headless SDK checkpoint: 216 tests and strict all-target Clippy pass after typed default Task jobs, active-socket lifecycle correction, authenticated incognito and explicit public anonymous SSE. Native CLI volatile-send fixtures pass 16 focused cases; four new profile/identifier tests verify separate per-origin identity, no credential access, logout stability and hostile-file rejection. New actual-executable anonymous evidence remains an ignored GitHub-only case using synthetic SSE, so it performs no real AI inference. Public Docs, account API-key lifecycle and authenticated protocol cases remain scheduled for the next exact-source CI candidate.

The broader native debug test run exposed a real default-stack overflow in the scoped Task-list dispatcher. Pure type-size measurements were only about 23 KiB per public dispatch future, but AArch64 debug poll-frame inspection showed roughly 652 KiB in the combined CLI context dispatcher and 954 KiB in the combined Task service dispatcher, before nested executor/HTTP frames. Heap-pinned command-family boundaries make the original failing scope test pass without increasing thread-stack settings. The private Task service dispatch is now split into independently boxed command arms: its poll frame fell to 40 KiB, with a 61 KiB selected list arm (the largest other arm is 155 KiB). The original test and a 4 KiB public-future size guard pass on unchanged default stacks. The resulting full native suite passes 298 tests, with four product/CLI cases ignored locally for isolated GitHub execution; strict all-target Clippy and scoped lint also pass.

Candidate `6ff4ad84862a3f68ae85d0c70b0c432a29e9ca04` captures that checkpoint.
The ARM64 release binary is pinned by SHA-256 and 145 source-input checks; it is
not installed. Native application run `39638075277` failed at `open_draft` with
`invalid_argument`, after authenticated workspace loading and API-key device
approval, Task/Project CRUD and revocation checks passed. Authenticated PTY and
paired application measurements were not reached. The failure is retained for
the next session; no further fix was attempted after the user's stop request.
Self-host run `39638081331` compiled the Rust CLI but failed before native setup:
the retained npm source baseline could not create `/app/data` beneath Vault's
read-only whole-source mount. The correction narrows read-only mounts to the code
files/package, preserving writable data and explicit environment mounts. No
self-host success or recording is claimed for that run; its failure receipt and
logs are retained, and evidence collection found no test attempt recording.

The platform source audit also identified Darwin device-ID and raw-mode width
errors and unconditional Unix imports that prevent Windows compilation. Those
are tracked implementation gaps, not target-native build results. Equivalent
Windows ACL, handle identity, durable storage, process-tree and terminal controls
remain required; successful Linux checks cannot admit desktop releases. The
Darwin width/bootstrap corrections subsequently passed eleven focused tests,
formatting and strict Clippy on Linux; actual macOS compilation is still pending.

## Paused handoff — 2026-10-21

Implementation stopped at the user's request. Reuse workspace `agent-d1c4` and
session `d1c4`; all four migration Tasks remain open. The npm command and source
are intact. There was no dev profile bootstrap, native installation or deployment.

Self-host request `f0b5601c98446d6864426403e65aa1284223d8b12ed22bb3e141cc288a7d78c3`
was submitted for source `b2413c71404c772f1ef8da22998590a8e53873cc`: exactly the
earlier `6ff4ad84862a` candidate plus the reviewed Vault mount correction and
six-test packaging regression. Retrieve its existing result before another run.
Current workspace changes after those candidates are not covered by their CI.

The maintained command inventory now contains 722 paths and 580 flags; its nine
focused source/mutation tests pass. It still declares completeness false. Newly
inventoried aliases are unsupported, and original two-selector Plan command
layouts remain parser gaps. Native browser-pairing coverage is written and passes
focused TypeScript checks, but still needs isolated execution and integration
after the exact native build. SDK capability publication remains blocked by 138
explicit gaps; the earlier 216-test SDK checkpoint and bounded three-library
conformance reports do not establish full capability parity.

Foreground remote access also remains a substantial application gap. Rust
envelope crypto, scoped Task-sync reducer/private cache and one-shot Codex
metadata/resume commands exist; they are not connected into a native source-host
runtime. Remaining joins include authenticated source registration/reconnect,
durable Task subscriptions/outbox delivery, protected remote files, command
authorization/lease/process confinement and persistent Codex presence/events.
Legacy Python/Node application helpers must be replaced by Rust, while the
existing backend and separate test harnesses remain permitted. The existing
protocol's bounded plaintext source-completion excerpt is a separate disclosure
boundary and must not be mistaken for encrypted remote command records.

The next actions and exact candidate/request identities are in the existing
[Plan](plan.yml). The first repair is the retained `open_draft` failure, followed
by essential exact-source CI proof, side-by-side native daily testing and then immediate browser integration. Full parity, security,
platform and SDK acceptance remain open; npm source retirement still requires
explicit acceptance from both the agent and user.

## Resumed shared-client architecture — 2026-10-22

The user confirmed all five architecture decisions and requested implementation
after updating the relevant Specifications. The approved CLI, SDK, synchronization
and storage-lifecycle bundles now define shared Rust application logic with thin
platform adapters. Twelve changed assertions have readable examples; the exact
bundle hashes, registry validation and generated agent mirrors pass. The existing
At that 2026-10-22 checkpoint, Plan and Tasks retained complete CLI/TUI before
web. That sequencing alone is superseded by the approved amendment above;
verified web still precedes Apple. Backend migration follows reliable client completion and
accepted removal of superseded code; it is not current implementation work.

Cargo installation and a separate SDK crate are the primary distribution route,
including versioned development prereleases. Downloadable GitHub executables are
out of scope. Linux and actual macOS verification are required; Windows testing
is waived without implying support. Web download overhead and application
performance must be measured against the original baseline rather than assumed.

The retained draft-only opening failure now has a narrow authenticated recovery
path after an exact metadata 404. It validates ownership, canonical draft version
and both encrypted fields, preserves rotated credentials, and fences cancellation
and expired sessions before publishing state. The full SDK suite passes 226 tests
(excluding a credential-isolation subprocess's repeated test), with strict
all-target Clippy passing. This is local fixture evidence; actual protocol CI
still needs to verify the repair.

Original two-selector Plan/Task add/remove layouts now parse into the existing
native delegation with the correct identifiers. Nineteen parser tests, eight
Plan tests, nine baseline policy tests and the reviewed baseline inventory pass.
The command catalog remains partial and explicitly declares completeness false.

Fresh and interrupted self-host projects now stage dependencies, Vault and CMS
setup before starting consumers. Vault starts before initialization establishes
its full health; completed live cohorts retain selected startup without forced
migrations. Incomplete live cohorts or active setup jobs refuse safely. Ten
startup fixtures and seven bounded diagnostic fixtures pass; independent review
cleared both startup findings. The full native suite passes 315 tests with four
product tests ignored locally, and strict all-target Clippy passes. The earlier
CMS unhealthy result lacked the underlying health log;
the schema-ordering explanation remains a hypothesis until isolated CI verifies
the correction. New diagnostics retain bounded, redacted setup and health details.

The CLI's embedded inputs and licenses are crate-local, with canonical provenance
checks, twelve packaging guard tests and only `openmates` installable as a binary.
The SDK source archive/input audit passes; registry resolution, consumer install
and macOS execution have not been verified. Publication remains disabled and
blocked by 138 explicit SDK capability gaps. Native browser-pairing coverage is
integrated into the CI proof flow and passes focused local tooling checks; its
actual browser/terminal execution is pending.

The installed dev command remains the npm implementation. No native profile
bootstrap, global replacement, old-code removal or full migration acceptance is
claimed. Actual authenticated TUI performance and self-host source/image lifecycle
evidence remain required alongside the original renderer and help/version results.

The resumed actual-library conformance run passes 33 Rust/npm/Python adapters and
201 vector executions using fresh current-source native bindings. The
[full report](sdk-conformance-resumed-2026-10-22.json) and
[input/artifact provenance](sdk-conformance-resumed-2026-10-22-inputs.json) retain
the source hashes, focused recovery results and five successful fresh Python
boundary processes. A stale recovery-peer foreground assertion was corrected to
the existing client contract, with negative coverage; canonical fixture vectors
and runtime source were unchanged. An earlier blank-stderr adapter exit remains
unexplained because the old tool lost its return code. Later passes do not prove
a cause or fix. New diagnostics retain exit codes and signals. All 138 capability
gaps and the release block remain intact.

Candidate `2628325b035a8e9b6e88899b54749243e930b610` passed draft opening in native
run `39832701558`, then failed deletion because the request omitted the backend's
required `chatId` alias. Self-host run `39832707017` passed the native source
lifecycle, then failed native image update; see the [retained phase audit](selfhost-ci-2026-10-22.json).
Its Linux ARM64
release binary is pinned with 147 source-input checks before and after build,
SHA-256 `c345938bcc4e5b691c32548fed6ad761e536e6496df9be7fee5a1215cae9aeb1`.
It is not installed. The conformance harness corrections occurred after this
candidate; no native application/SDK build input changed.

Subsequent SDK fixes add that deletion alias and strict successful draft-save
receipts, use the durable title-only rename route with canonical independent
versions, and fence terminal persistence and echoed embed identities. The SDK
suite now passes 245 tests; the application suite still passes 315. Both strict
all-target Clippy checks and independent source review pass. Fresh bindings pass
all 33 adapters/201 vector executions again; see the
[current report](sdk-conformance-ack-fixes-2026-10-22.json) and
[new source/artifact provenance](sdk-conformance-ack-fixes-2026-10-22-inputs.json).
The previous unexplained process exit and all 138 release-blocking gaps remain
open. Native protocol coverage adds actual encrypted empty-chat rename/readback
without AI. Candidate `dc7f6a6d80316721afc6ab050d97fbd4560ed964` is running in
native CI `39840473316`; the run failed at draft deletion. Retained server logs
confirm that `chatId` is now accepted, then the saved-chat recovery deletion fence
rejects the draft-only ID with `chat_not_found`. The existing `delete_draft`
protocol must handle that case. Rename, authenticated PTY, pairing and benchmark
execution were not reached. Its Linux ARM64 release binary is privately pinned with 149 input hashes
verified against that source before and after compilation, SHA-256
`d31355769083606ebdd3ec1b36528595fd21ff6ebc6763e943b0d95c8d117520`.
It is not installed, and no signed build attestation is claimed.

The [SDK package audit](sdk-package-audit-2026-10-22.json) verifies 89 canonical
inputs against the captured source and compiles the actual extracted archive
plus a separate headless path consumer with locked offline dependencies. The
consumer passes local crypto, wrong-key and explicit-client construction checks
with empty HOME and no executable PATH. This proves that bounded source-package
use, not registry resolution, application installation, macOS support or release
parity. Cargo's generated VCS metadata still describes the dirty checkout base;
the separate input hashes establish the exact captured SDK source.

The next local checkpoint adds canonical Personal draft clearing and native
Cookie chat metadata search. Final SDK tests pass 260 cases; complete native
checks pass 322 with four product cases ignored locally. Strict Clippy passes
for both. Search covers the recent 100-chat window plus discovered drafts;
older-chat census, API-key/example and TUI search, local-date/ANSI presentation
and search-specific cross-language proof remain gaps. A new isolated history
fixture passes nine mocked tests, TypeScript/lint and independent review; actual
seeding, both-client readback and authenticated timing are still unverified.

Fresh final bindings again pass [33 adapters/201 vectors](sdk-conformance-search-draft-clear-2026-10-22.json)
with [execution provenance](sdk-conformance-search-draft-clear-2026-10-22-inputs.json).
Only matrix gap prose changed after that run's completed fence; runtime sources,
APIs, statuses, fixtures and runners did not change. The raw report remains
unmodified. This shared subset does not prove complete SDK or new search/draft
parity, and the earlier unexplained Python exit remains open.

Self-host image diagnostics identify two independent issues: the strict update
client probes the redirecting `/health` path, and new provider directories were
private to the installer UID. The fix probes canonical `/v1/health` directly and
creates new public provider directories as 0755 while preserving existing
private/custom directories and secret files. Four focused tests and independent
review pass; actual corrected image install/update remains required in CI.
