# Browse qualification — 26 October 2026

Backend qualification is in progress. These are development measurements, not a
claim that web embeds, workflow support or general browsing acceptance are complete.
The approved contract is `feature.app-skill.web-browse@1`.

The deployed backend (`29836d6`) has a successful real CLI JSON extraction,
successful direct npm extraction, native idle pause/resume and successful direct
Python replay of the closed npm run. Later fresh SDK outcomes are recorded below.
The previous object-storage outage recovered; the retained CLI recording and new
CI evidence uploaded successfully. Backend commit `612c62f` passed 113 focused
cases plus the first-party HTTP authorization case in isolated CI (runs
40384854217 and 40384953480). The pool remained disabled during deployment and
was enabled only after the live synthetic-owner qualification below passed.
The coordinated runtime restart completed with all 17 services healthy. The live
configuration has three prepared paused VMs. Fresh app/SDK measurements confirmed
the provisioning improvement but exposed the verification failures below.

## Startup optimization qualification

Provider probes use actual E2B resources without AI calls. All qualification VMs
were destroyed. They do not establish web-embed or general task acceptance.

| Path | Samples | Browser-ready time | Result |
| --- | ---: | --- | --- |
| Original cold startup | 3 | 10.196–20.316 s | Misses user limit |
| Prestarted Chromium template, fresh allocation | 10 | 3.443–9.356 s; median 6.657 s | Preboot alone is insufficient |
| Prepared, confirmed paused blank VM | 5 | 1.240–1.841 s | Initial immediate-resume prototype |
| Durable assignment after 125 s paused | 2 | 1.568, 2.024 s | Includes SQL claim, owner-key handoff, credential scrub, resume and live pristine check |
| Three simultaneous durable assignments | 3 | 2.128, 2.197, 1.663 s | Three distinct VMs; no shared profile |

The accepted goal is under three seconds, acceptable below four, with four to
five seconds the hard ceiling. The five full handoffs stayed below 2.2 seconds;
this is a small development sample, not a production percentile guarantee.
Individual blank preparation took 2.881–9.387 s in the initial probe and happens
before a user request. An IPv4-only diagnostic did not improve the cold path and
was not adopted.

The live test uses the documented HTTPBin `/base64` endpoint to serve our own
fixture under its ISC licence. It writes only synthetic random markers and
reports booleans. Cookies, local storage, session storage, IndexedDB and Cache
Storage were present for owner A, absent for owner B, and still present when A's
original browser resumed. An A bearer was rejected at B's endpoint. A real
primary-key race granted only one of two claims for the last blank VM. A full
pool returned no handle on exhaustion, and all claimed rows had removed their
platform credential copies. Synthetic rows, VMs and test Vault keys were cleaned
up. This native/Vault qualification complements the CI API boundary case; it does
not substitute for real CLI/SDK or GUI proof.

Each prepared VM is assigned once for its entire lifetime. Claimed VMs are never
recycled, including failed handoffs. Immutable database receipts arbitrate
ownership, and encrypted owner persistence plus platform credential removal
precede user work. Paused compute is free under E2B's current billing policy.
Unassigned preparation is platform overhead, with no change to the user's
approved 2× tariff after admitted resume. Pool size and replacement lifetime need
tuning against measured demand. No Kernel infrastructure was required for these
results.

## Deployed full skill checks after pool activation

Fresh direct npm and Python requests at the pool-only revision provisioned in
2.328 s and 2.244 s. Initial navigation took 4.174 s and 2.759 s respectively;
initial setup including persistence/navigation was 6.839 s and 5.776 s. Both jobs
later failed when corrective Gemini calls exceeded 20 seconds. Those VMs are
closed. Unknown supplier usage remains held for reconciliation and is not a zero
bill or a successful extraction. The assistant CLI attempt also failed and then
reached its spending guard; it settled at 22 credits.

After checked-quotation verification (`5d2048a`), **fresh direct npm and Python
requests both passed**, returning the entire observed English quotation and source
URL. No replay or CLI subprocess stood in for either library call.

| SDK | Provisioning | Initial navigation | Full initial setup | In-skill total | Submit through result | Settled after Close |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| npm | 3.540 s | 4.537 s | 8.368 s | 17.289 s | 22.769 s | 8 credits ($0.008) |
| Python | 3.762 s | 3.624 s | 8.179 s | 18.100 s | 23.331 s | 8 credits ($0.008) |

Provisioning stayed below four seconds in these runs; destination loading and
initial setup took longer and are not included in that browser-ready figure.
At result delivery each had accrued four credits, with native usage complete and
no reconciliation flag. The final eight-credit charges also include active time
between result delivery and Close. These two examples do not estimate all tasks.

The natural-language assistant call at that same revision omitted output_schema.
Its different path returned raw tables/links/text as if that snapshot were the
requested answer, then failed verification. It provisioned in 2.808 s, completed
initial setup in 6.132 s and returned needs_user after 8.582 s; the assistant used
web.read afterward. This is a Browse failure despite a successful terminal exit
and a final assistant JSON response. Its VM is closed. The latest successful CLI
recording remains the older baseline run.

Native controls reproduced a false rejection of the complete English quotation
(grounding 0.88, coverage 0.41). Shorter questions still rejected it. Standalone
extraction controls returned the full text in 1.724–3.087 s, so they did not prove
a causal timeout fix. The deployed quote path instead matches every string value
to observed evidence before a separate, metered semantic review; original Jev
thresholds, action checks and output safety remain intact. Five native positive
and negative controls passed, as did 77 model/service cases in isolated CI (run
40393393048). Its complete-quote helper control took 3.862 s and cost $0.00098025
supplier USD in addition to Jev.

The next candidate also extracts an answer when the caller omits output_schema,
using a default object schema while preserving full observations separately.
A native control of that path produced the requested statement/URL and passed
independent verification; 42 local service cases passed, including metering,
replay and rejection of a scalar default answer. Isolated CI and deployment of
this correction are pending.

## Environment and scope

E2B hosts Chromium in a prepared Playwright 1.64.1 image with 2 vCPU and 4 GiB RAM.
The prepared browser path must also be passed in the sandbox runtime environment:
E2B template environment variables apply during the image build only.
The live assistant test uses automatic routing. Browse itself uses Jev 1.14;
the text/extraction calls used Gemini 3.8 Flash. Together's verified organization
retention flag remains disabled, so these results do not qualify the DeepSeek primary.

Tests use an isolated CLI profile, disposable Project and temporary SDK key with
a daily credit limit and expiry. No account defaults or model overrides were changed.
The temporary SDK key is now revoked and its local secret material removed;
the non-secret revocation receipt and qualification evidence are retained.

## Initial measurements

| Measurement | Observed value | Scope |
| --- | ---: | --- |
| E2B creation and browser readiness | 20.702 s | Standalone live provider probe |
| Page observation | 1.077 s | Same provider probe |
| Explicit pause | 0.352 s | Native paused state confirmed |
| Resume | 0.497 s | Same page preserved |
| Peak sampled VM memory | 495,980,544 bytes | One simple page; not a general peak |
| First skill startup, including initial navigation | 11.616 s | Direct npm library call |
| First skill execution | 16.713 s | Returned `needs_user` for an absent heading |
| First npm request through result delivery | 22.253 s | Includes admission, queueing and polling |
| Internal inference | 3 calls, about 3.057 s | Two Jev calls and one Gemini extraction |
| Native automatic idle pause | Confirmed after 125 s | Fixed long-lived controller; same page retained |
| Resume after automatic idle pause | 0.460 s | Latest native lifecycle probe |
| Latest native cold readiness | 10.990 s | Same lifecycle probe |
| Latest peak sampled VM memory | 492,797,952 bytes | Same simple-page probe |
| Verified npm structured extraction | 28.489 s | 26.231 s inside the skill; startup 21.282 s |
| Verified real CLI extraction | 28.910 s inside the skill | Startup 22.044 s; explicit required JSON fields |

The page had no visible heading. The requested schema required one, so Browse
returned `data: null` and declined to claim completion. This is retained as a
negative extraction case, not counted as successful task fulfillment. Browser
resource and native inference usage were recorded, but settlement verification
and a successful structured-data case are still pending.

## Cost basis

Using [E2B's published rates](https://e2b.dev/pricing), supplier compute is
$0.000046 per active second at the selected resources:
2 × $0.000014/vCPU/s + 4 × $0.0000045/GiB/s. At the approved 2× multiplier,
compute contributes $0.00552 per active minute before model calls and cumulative
credit rounding. One credit is $0.001.

The first extraction attempt accrued supplier cost of $0.0015078672 at result time:
$0.0006905448 compute and $0.000817326 inference. Its result reported 3 accrued
credits and 0 settled credits while the live window was still open. The final
session charge must also include any subsequent active grace or follow-up work.
Ordinary assistant preprocessing and response charges are separate.

The successful npm extraction accrued supplier cost of $0.00210999433791351318
($0.001171525847434997578 compute and $0.000938472 inference) at result delivery.
The successful CLI extraction accrued $0.002244211552955627422 supplier cost,
including $0.000952452 inference. Both reported 4 accrued credits before idle
settlement. After idle pause and Close, the successful CLI session settled at
**14 credits ($0.014)**. Its final supplier cost was $0.00742042491517257696:
$0.00646797291517257696 compute plus $0.000952452 inference. An independent
Decimal calculation confirmed the approved cumulative 2× floor/minimum rounding.
This measured price includes the active idle allowance; outer chat charges remain
separate. It is one simple-page task, not a general task-price estimate.

That CLI run recorded 9,759 native input tokens and 238 output tokens across four
calls. The three Jev calls took 0.218, 0.224 and 0.170 s; Gemini extraction took
3.830 s. The remaining skill time is primarily cold browser setup and observation.

E2B confirmed a paused sandbox with preserved state. [Paused compute is free](https://docs.e2b.dev/billing);
the application deletes an idle session after 24 hours. The full 24-hour wall-clock
expiry has not been observed; lifecycle boundaries have deterministic coverage.
The optional two-minute active idle window alone contributes up to $0.01104
at the user multiplier before rounding.

## Reliability findings and fixes

- Unsupported E2B firewall CIDRs rejected creation. Supported private-network
  exclusions and DNS-pinned public HTTPS transport now pass the native probe.
- A browser installed during image build was absent from the runtime search path.
  Supplying the runtime path fixed readiness; all 13 transport cases passed in CI.
- The first real assistant call selected Browse but timeout validation rejected
  private dispatch fields. Public request validation now excludes internal context
  while continuing to reject unknown public fields.
- Native Google proto3 responses can omit a zero cached-token counter. Browse
  normalizes that documented default only when successful usage totals are complete.
- Resume exposed an unsupported reservation-release reason. Paid charges already
  settle their reservations atomically; zero-charge windows use the supported
  release path. Pending charge receipts retain their intent and reservation.
- A follow-up must reconcile E2B's native idle pause before changing activity and
  admitting resume. Regression cases cover one original browser and stable charges.
- An initial 125-second native idle probe confirmed auto-pause, then reproduced HTTP 502 on
  the first browser RPC after successful resume. The current candidate waits on
  bounded metadata-only readiness checks and never retries an input action.
  The readiness wait alone did not restore an older controller.
- A subsequent 75-second A/B probe isolated the controller lifetime: both VMs
  were still running at the same ingress addresses, but the default command had
  zero controller processes and returned 502; `timeout=0` retained one responding
  controller. The deployed fix explicitly disables the SDK's default 60-second
  command connection timeout. The sandbox's idle/expiry lifecycle still bounds
  the controller. The native regression probe now supports `--idle-before-pause`.
  That probe subsequently passed automatic pause and same-page resume in 0.460 s,
  including private-network and manual-observation guards.
- Mouse-driven navigation can invalidate an observation's execution context.
  The deployed controller retries that read at most three times after document
  readiness; access denials and a closed original page are not retried.
- The initial completion question conflated factual support, answer coverage and
  website actions. A later generated answer included the complete visible purpose
  and caveats, yet the combined judge still rejected it. The candidate now asks
  those questions separately and supplies the trusted source reference that will
  be returned with the data. Native diagnostic controls scored a full verbatim
  answer 0.95 for grounding, 0.93 for coverage and 0.97 for browser actions. Omitted
  caveats scored 0.67/0.03/0.89; an invented banking claim 0/0/0.90; unfinished
  required navigation 0.52/0.15/0.08. Acceptance requires grounding and completed
  interactions at least 0.95, with coverage at least 0.90. These are heuristic
  cutoffs from a small control set, not measured accuracy probabilities. Explicit
  zero-result acceptance also requires completed website interactions.
- A separate information-readiness question scored visible information 0.97,
  required navigation 0.16 and an absent heading 0.54. The next candidate uses
  that head to avoid unnecessary navigation, with independent final verification
  still required. It never overrides a page-injection block.
- Successful native resume is now persisted before ingress checks. A later
  transport failure can settle its known compute window rather than treating the
  entire resume as unknown. Closing an unresolved session retains only the private
  resource identity/counters needed for billing review while removing credentials.

The retained real session recovered its interrupted settlement and reported 12
charged credits. Its subsequent browser resume still failed before readiness;
it is not a successful reuse case. The CLI's next run dispatched Browse, returned
a failed Browse result and recovered through `web.read`. That is a Browse failure
despite the CLI process exiting successfully.
The next CLI attempt successfully navigated to IANA and reused the active browser,
but completion scores of 0.63 and 0.49 led to `needs_user`; the assistant again used
`web.read`. This remains a failed Browse fulfillment check. An older SDK session's
failed resume has a reconciliation hold; its last confirmed settled charge is 13
credits. That hold is not a new settled charge and must not be silently forgiven.
The legacy session has now been closed: live credentials are removed and only the
private resource receipt needed for reconciliation remains. The latest CLI run
stayed on the intended Example page but again returned `needs_user` and fell back
to `web.read`. The latest npm call likewise returned no verified data: readiness
scored 0.95 and the old combined completion question 0.85. Neither is a Browse
fulfillment pass. Its 26.172 s includes 21.201 s of cold startup; accrued supplier
cost at result time was $0.00200887587929, before final idle-window settlement.

The deployed dispatch, settlement and pause-recovery change passed 32 focused
tests locally and in isolated CI (run 40336127998). The preceding broader backend
and Google SDK check passed 88 tests. The readiness/observation candidate passed
61 focused local tests before five additional transport cases, which also passed.
The deployed readiness candidate subsequently passed 67 isolated cases (run
40342501601). The controller-lifetime/native-receipt/information-readiness candidate
passed 74 focused cases locally and in isolated CI (run 40349555582).
Native provider probes are additional evidence;
they do not replace CLI, SDK or web acceptance.

The separated rubric subsequently passed 83 focused cases locally and in isolated
CI (run 40356071535), and deployed as `29836d6`. A fresh npm call returned verified
JSON containing the full English statement and source URL. A clarified real CLI
request with two required fields also returned completed Browse data, without a
`web.read` fallback. The broader preceding CLI request still abstained (coverage
0.82); a Python follow-up abstained on browser state (0.92), and a fresh Python
call omitted requested content (coverage 0.48). These failures remain part of the
qualification; a single successful page extraction does not establish a success rate.

A retained 40-credit session resumed but stopped before extraction with 15 credits
settled. The next operation's conservative maximum inference quote exceeded its
remaining headroom. A later session executed one required link click in 0.382 s,
then stopped at its budget guard with 21 cumulative credits settled; that is not a
completed navigation/extraction task. Cap admission reserves maximum operation
cost, while settled charges use actual native usage. Six older test sessions have
now been closed with settled charges of 12, 3, 22, 12, 15 and 21 credits, each
without pending accounting. The separate legacy 13-credit session still retains
its unresolved reconciliation hold.

The next candidate permits one metered correction of a rejected structured
answer using only the same observed page. Every candidate must independently
pass the unchanged grounding/coverage/browser-state checks. An absent candidate
or explicit request for human input stops immediately. Focused local coverage
now passes 88 cases, including successful correction, continued rejection,
missing facts, all extra inference charges and replay without further spending.
An unchanged correction cannot seek a second stochastic verification verdict.
The budget stop message now distinguishes insufficient operation headroom from
having already spent the entire session cap.
Exact-source isolated CI and fresh deployed Python acceptance are next.

Publication of that candidate is blocked before CI submission: authenticated
`HeadBucket` calls return 503, as do public HEAD requests from both the host and API
container. The selected successful CLI recording upload also failed with 503;
the original 71-second real terminal recording is retained locally. Existing
source and successful proof were preserved during disk cleanup; the disk reserve
recovered to 33 GiB. No check was bypassed and the correction is not deployed.

On the exact deployed Browse source, direct Python replay of the completed npm
request after Close returned the identical run, JSON and native metrics. An
owner-scoped before/after record audit confirmed unchanged compute/inference cost,
21 settled credits for that multi-run session, no pending accounting and no live
provider. This is genuine closed-session idempotency and SDK transport proof;
it does not qualify a fresh Python extraction. All known retained test browsers
are now closed. The unresolved legacy accounting receipt remains preserved.

## Optimizations to evaluate after functional acceptance

1. Pause immediately after a verified completed task, retaining the two-minute
   idle allowance for active human interaction. Fast measured resume could avoid
   much of the idle-window cost for short tasks; this changes the approved lifecycle
   behavior and needs a recorded decision before implementation.
2. Benchmark 2 GiB RAM at the same CPU count. Its theoretical compute saving is
   about 19.6%; the single-page memory sample does not prove adequacy for heavy sites.
3. Bake and warm the trusted browser runtime to reduce first-use setup. Keep cold
   creation separate from resume measurements and verify the actual saving.
4. Expand permitted tasks and missing-data cases before reporting a success rate.
   Add visual localization only after presence and geometry checks are evaluated.
5. Exercise provider snapshot backlog and resume failures. E2B documents that an
   auto-pause may fall back to a filesystem-only snapshot after repeated memory
   snapshot refusals. The app must report an unavailable original browser rather
   than silently substitute another session. Native lifecycle events would improve
   diagnosis and resource reconciliation. See [E2B persistence](https://docs.e2b.dev/sandbox/persistence).
6. Reduce excessive admission headroom with provider-supported token counting and
   schema-sized output limits, preserving valid cost upper bounds. The current
   UTF-8 input bound plus a 2,048-token output ceiling can block a continuation
   well before its settled spending reaches the session cap. Report insufficient
   operation headroom distinctly from exhausted actual spend.

## Remaining acceptance

CLI/npm extraction, final settlement and cross-SDK closed-session replay are
verified on the deployed version. Fresh Python execution, the correction's
isolated CI/deployment and broader permitted-task acceptance remain pending.
Rust parity is unavailable until the separate Rust migration
lands or the user explicitly defers that phase prerequisite. Web screenshot embeds,
watch/takeover/private sign-in/continuation and laptop/mobile proof follow the CLI
and required SDK gate. Workflow verification follows the regular skill and embeds.
