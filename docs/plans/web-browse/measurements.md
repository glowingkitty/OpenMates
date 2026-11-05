# Browse qualification — 26 October 2026

Backend qualification is in progress. These are development measurements, not a
claim that web embeds, workflow support or general browsing acceptance are complete.
The approved contract is `feature.app-skill.web-browse@1`.

The pool and verification changes are deployed through `46e7c36`. The shared
runtime subsequently advanced to `09d92f3`; owned Browse source hashes matched
before paid tests. All services were healthy. Fresh npm/Python calls and the real
assistant JSON-extraction flow passed. A first-party call with an explicitly null
schema also passed. The multi-step navigation case reached its target but abstained
on answer verification, so general browsing reliability is not established.

The earlier storage outage recovered. CI evidence and the latest selected CLI
recordings uploaded successfully. The pool revision passed 113 isolated cases and
HTTP authorization/pool-reassignment rejection (runs 40384854217/40384953480).
The latest extraction correction passed 79 model/service cases (40397671017).
The running pool has three prepared paused VMs; all known test sessions are closed,
temporary SDK keys are revoked, and local key secret files are removed. Earlier
unknown-usage reconciliation holds remain preserved, not forgiven.

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
and a final assistant JSON response. Its VM closed and settled at 11 credits.
The subsequent successful CLI check below supersedes that failed attempt.

Native controls reproduced a false rejection of the complete English quotation
(grounding 0.88, coverage 0.41). Shorter questions still rejected it. Standalone
extraction controls returned the full text in 1.724–3.087 s, so they did not prove
a causal timeout fix. The deployed quote path instead matches every string value
to observed evidence before a separate, metered semantic review; original Jev
thresholds, action checks and output safety remain intact. Five native positive
and negative controls passed, as did 77 model/service cases in isolated CI (run
40393393048). Its complete-quote helper control took 3.862 s and cost $0.00098025
supplier USD in addition to Jev.

The correction now deployed at `46e7c36` extracts an answer even when the caller
omits output_schema, using a default object schema while preserving observations
separately. Local service checks passed 42 cases; the combined 79-case model/service
suite passed isolated CI. A retained-observation native control and an explicit
null-schema first-party call both passed.

| Latest flow | Provisioning | Initial navigation | Initial setup | In-skill time | Outcome / final Browse charge |
| --- | ---: | ---: | ---: | ---: | --- |
| Real assistant, Example JSON | 3.967 s | 4.148 s | 8.441 s | 18.652 s | Completed, exact full quotation and URL; 14 credits ($0.014) |
| First-party null schema, HTTPBin HTML heading | 3.241 s | 3.694 s | 7.705 s | 17.988 s | Completed, heading/URL object; 16 credits ($0.016) |
| Real assistant, follow Learn more to IANA | 1.901 s | 3.839 s | — | 17.353 s | One click reached IANA; verification returned needs_user; 17 credits ($0.017) |

The explicit null-schema call took 23.242 s from submit through result. Its first,
separate 30-credit-capped attempt stopped at the conservative next-operation bound
before extraction; a new 60-credit session succeeded. The stopped session closed
at one credit. The successful assistant's terminal output spanned 73.180 s, and its
raw recording is 76.800 s including capture lead/trail. Thus the 18.652 s skill time
is not end-to-end assistant latency. Ordinary assistant processing is separate.

The navigation click took 0.325 s. The verifier's interaction score was 0.85,
grounding 0.93 and coverage 0.88; no unverified JSON was returned. The regular
assistant then used web.read. That remains failed Browse task fulfillment, with a
retained failed recording. The checker currently sees the final page rather than
a full, code-verified navigation history; enriching that evidence is a recommended
reliability investigation, not a demonstrated fix.

Independent owner-scoped Decimal audits confirmed all four recorded charges:

| Flow | Final supplier USD | Compute USD | Internal inference USD | Credits at cumulative 2× floor/minimum |
| --- | ---: | ---: | ---: | ---: |
| npm JSON | 0.004350288022499084620 | 0.002914308022499084620 | 0.001435980 | 8 |
| Python JSON | 0.004330252029949188360 | 0.002894146029949188360 | 0.001436106 | 8 |
| Assistant JSON | 0.007399768619918823120 | 0.005953618619918823120 | 0.001446150 | 14 |
| Navigation abstention | 0.008933508032901764040 | 0.005520000032901764040 | 0.003413508 | 17 |

These charges include active time after result delivery, up to native idle pause
or explicit Close. They are not four-second startup prices. Pool credential copies
were empty for every audited claimed VM, and closed records retained no live
provider credentials. Failed tasks can still incur their actual metered cost.
The new temporary SDK key was revoked after qualification.

## Next optimizations and delivery limits

- Keep E2B: prepared paused resources met the infrastructure target in this small
  sample. No Kernel account or credits were used.
- Provisioning is below four seconds in the recorded deployed cases, while initial
  destination setup still takes roughly six to eight seconds. Stream a safe ready/
  loading preview during navigation and measure the first visible frame in the web
  implementation; no first-visible-frame claim is made before that UI exists.
- Profile caller admission, queueing, observation and ordinary assistant inference
  separately. The full assistant request remains much slower than provisioning.
- Add code-verified action provenance to completion evidence, preserving negative
  controls; do not lower thresholds merely to accept uncertain answers.
- Tune paused-pool capacity/refill against burst demand. Empty capacity returns a
  bounded rejection without cold fallback or user preparation charges.
- Qualify smaller allocated RAM against representative sites before reducing cost;
  the approximately 493 MB simple-page peak does not establish general browser needs.
- Together/DeepSeek primary qualification still needs the required organization
  retention verification. Current native helper results qualify Gemini fallback.

Screenshot/fullscreen browser embeds, takeover UI, two app-store examples, Rust
SDK parity and workflows remain unfinished. Workflow acceptance follows normal
skill/embed delivery. The approved Specification and app-skill skill currently
require Rust/npm/pip SDK proof before web work. This checkout has only a Rust TUI
prototype and Apple crypto bridge, with no Rust SDK; the earlier requested deferral
has not been answered. No Rust parity, web-viewer or workflow success is claimed.

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

## Web embed implementation (2026-10-27)

The user explicitly authorized continuing web embeds while Rust SDK parity is
unavailable. CLI and direct npm/Python execution and settlement are verified as
recorded above. Rust remains deferred, rather than implemented or verified.

The candidate adds Browse preview/fullscreen routing (including grouped embeds),
actual task outcomes, lossless saved JSON, encrypted early session identity,
owner-only live frames, watch/takeover, contextual sign-in consent, normal-chat
continuation with the same session and spending limit, and pause/close controls.
Account/view changes abort requests and release private frame URLs. Viewing does
not resume compute or extend inactivity. All 21 locales have control labels and
privacy/lifecycle guidance; the exact continuation instruction retains its English
machine field names in every locale.

Local focused verification: 26 frontend unit tests and five dispatch tests pass.
The three Browse components compile. The repository-wide Svelte check reports
521 existing errors elsewhere; no Browse component/service error was reported.
Isolated component/browser CI and actual deployed takeover remain pending. This
candidate has not yet established first-visible-frame latency or end-to-end UI
performance. Do not substitute the earlier provider provisioning measurements for
those user-visible measurements.

## First real web run on 27 October

Dev commit `970c0d6` is deployed and its backend workers are healthy. The
preview/fullscreen/control components passed isolated laptop/mobile verification
(run `40484678836`); the new dispatch case passed run `40479876763`.

The first real CLI-created HTTPBin heading task, chat `8693ccf6`, failed Browse
answer verification and the main assistant used Read instead. This is a failed
Browse fulfillment, regardless of the successful outer chat response. Its first
run measured 2.859 s provisioning, 15.868 s skill time and 78.587 s outer CLI time.
The browser was closed through its owner API and settled at 13 credits with no
pending accounting. Complete native usage was reported. The old failure receipt
retained only `BrowserModelError` at verification, so its exact text-helper
failure is unresolved. A prepared revision normalizes a single complete JSON
code fence and records allowlisted error codes, response shape/length and helper
purpose without page text, response text or credentials; acceptance thresholds
are unchanged.

The separate GUI check opened an authenticated shell with blank encrypted
messages before reaching Browse. The harness had round-tripped IndexedDB through
JSON; loss of the native master CryptoKey is the leading harness hypothesis,
not a confirmed causal diagnosis. The correction uses a
private persistent browser profile, checks the native key type and a known real
chat before spending on inference, and keeps authentication unrecorded. The
manual sign-in cases did not run. No real takeover/continuation success is
claimed yet.

Deployed visual review also found that a read-only terminal result with no
screenshot incorrectly said it was waiting. The prepared UI correction gives an
explicit missing-screenshot state; the existing successful extraction data is
unaffected. This correction still needs its isolated check, deployment and visual
review.

## Remaining acceptance

Complete isolated component proof, authenticated web flows, dev deployment and
reviewed laptop/mobile evidence, followed by the two real app-store examples.
Workflow verification follows delivery of the regular skill and embeds. Rust SDK
parity remains explicitly deferred by the user’s 2026-10-27 decision.

## Resumed web verification on 28 October

Hardening commit `d29e12d` is deployed to dev. Exact candidate `8fb0ff65`
passed isolated component run `40662199554` (three laptop/phone cases) and
backend run `40662282222`. The deployed fullscreen missing-screenshot state was
reviewed on laptop and phone with no clipping, broken images or console/network
errors. Managed backend operation `docker-a3eb0bd7` completed with all services
healthy; live inference checks verify the owned backend source under a shared
runtime lease.

The native persistent-profile preflight preserved its real master CryptoKey and
displayed an existing encrypted chat. A new automatically routed CLI chat
`110441e8` returned a genuinely completed Browse result containing the exact
HTTPBin heading and source URL. Its timings were 3.438 s provisioning, 3.600 s
initial navigation, 7.816 s startup through first observation, 17.524 s total
skill execution and 50.965 s outer chat. Provisioning met the below-four-second
target; the first observed page and full task remain substantially slower.

At skill completion, native supplier cost was $0.0029748241, including
$0.0007129600 runtime and $0.0022618680 inference; accrued user cost was five
credits. Five helper calls reported complete native usage. The session was
closed after the failed UI harness waited through idle grace, with a final
15-credit ($0.015) charge and no pending accounting. This final charge includes
that additional running time; it is not the immediate task-completion price.
Together ZDR remains unqualified, so the text helper used Gemini 3.8 Flash.

The remaining UI assertion failure was a test interaction: the completed skill
card was inside the standard collapsed assistant activity section. Authentication
and chat hydration succeeded. Persistent-browser video finalization then masked
that assertion by calling `video.saveAs` after its browser connection had closed.
The prepared harness expands the existing accessible activity controls and copies
the finalized local recording without a post-close protocol request. It also
records the admitted session before waiting for a frame so failed checks can
still close their own browser. Real takeover acceptance is still pending.

A reviewed component screenshot also exposed an expired viewer's misleading
watch/take-control hint. Its focused correction and assertion are preserved
locally. Further CI source publication is waiting on the central disk coordinator
(request `74484f99`); no independent cleanup or admission bypass is being used.

The next run, chat `ea57b800`, also completed Browse with correct JSON: 3.230 s
provisioning, 8.768 s through first observation, 28.882 s skill time and 58.948 s
outer chat. Final owner-close settlement was 18 credits with no pending
accounting, again including idle grace during the UI failure. It exposed the
actual viewer integration bug: the normal owner fullscreen has both `chatId`
and `lookupChatId` set to the originating chat. Rejecting every lookup hid all
live controls, even though the saved screenshot and JSON rendered correctly.
The prepared correction requires an explicitly private owner context, permits a
lookup of that same chat, and continues to deny public, shared, cross-chat and
unauthenticated views. Real test response waits are now bounded to surface a
missing owner viewer promptly. Disk capacity was subsequently granted by the
coordinator, allowing the corrected candidate to proceed to isolated verification.

Owner-viewer correction `f1b7809` is deployed, passed eight focused owner/frame
tests and component run `40667470064`, and its expiry state was reviewed on both
viewports. A third real task, chat `2acca599`, completed with correct JSON in
14.567 s (3.069 s provisioning, 7.550 s first observation, 41.325 s outer chat).
It accrued three credits at completion and settled at 13 after idle grace and
owner close, with no pending accounting. The viewer now mounted, exposing a
separate transport defect: Caddy's broad public API handler substituted wildcard
CORS, which browsers reject with credentials. A read-only replay of an existing
closed owner session confirmed CORS failure without further inference; an
approved CLI read of the same session succeeded.

The prepared transport correction adds the narrow Browse session path to the
first-party proxy handlers for preflight and actual requests. A saved-owner CORS
preflight now runs before paid acceptance requests. The live host also returned
wildcard headers for the repository's generic app-skill ingress, so moving the
URL would not fix this host; the control API remains stable. Non-interactive
sudo requires a password, and no privileged proxy reload or production service
change was made. Real takeover and sign-in remain unverified until the proxy
correction is applied and the live tests pass.

An owner-scoped usage-ledger audit included the ordinary assistant charge as
well as the settled browser charge:

| Chat | Browse credits | Assistant credits | Total user price |
| --- | ---: | ---: | ---: |
| `110441e8` | 15 | 9 | $0.024 |
| `ea57b800` | 18 | 9 | $0.027 |
| `2acca599` | 13 | 10 | $0.023 |

Each chat has exactly one Browse and one assistant ledger entry. Browser totals
include the idle grace consumed while the web test failed; task-completion
accrual alone was 5, 7 and 3 credits respectively. These are three successful
static-page extractions, not a representative web-task success-rate estimate.
The reviewed CORS patch is published at `c7df343`; 23 local configuration tests
pass. The operator applied the scoped, coordinated helper at
`/tmp/openmates-browse-d7bf-cli/apply-browse-caddy.py` after entering sudo's password
locally. Live headers now preserve the exact dev origin and credentials. A
read-only authenticated replay of a closed owner session returns 410 and shows
the expected expired viewer instead of a CORS error. Fresh control-transfer
acceptance is running. No production operation was performed.


### Real control flow after the proxy correction

The main real-inference browser acceptance passed for desktop controls and
390-pixel saved history: exact HTTPBin JSON, authenticated watch, exclusive
takeover, pause with free compute, resume, owner close and history reload. Chat
`3ea7b625` took 43.853 seconds through the outer CLI; opening its completed
owner viewer to its first live frame took 2.512 seconds. The closed session
settled at ten Browse credits, with no pending accounting. The actual usage
ledger adds seven assistant credits: 17 credits ($0.017) total.

Two desktop manual demo-login runs (`3e554cff` and `ce3579d4`) entered only the
fixture's published disposable credentials through owner controls, displayed
the contextual consent notice, and continued the same browser to a genuinely
completed Secure Area JSON result. The first continuation took 5.238 seconds.
Their browser-test assertions failed because they first reopened the oldest
card, then assumed exactly two cards despite the continuation message also
referencing the initial embed. Those assertions are corrected to select the
completed outcome, while retaining same-session, original-budget and exact-JSON
checks. Final desktop/phone sign-in acceptance is pending coordinated runtime
admission; no success is claimed for those full test cases yet.

The two manual chats settled at 31 credits (8 Browse + 23 assistant) and
36 credits (17 Browse + 19 assistant), including manual interaction and test
waits. Session close cleanup completed. The first extraction example
(`02a441f4`) settled at 87 credits (14 Browse + 73 assistant); this demonstrates
why ordinary chat routing can dominate a simple browser task's full price.

Native Browse ledger entries currently lack their triggering message identity.
The account/chat totals above are complete, but response-level example pricing
would omit Browse charges without a verified attribution. Correct that linkage
before treating the response-price label as complete.

Workflow investigation found that the current runner rejects async Browse and
that scheduled report delivery allocates a chat ID before an owner client
creates its encrypted chat. That pending ID cannot be used as a real source
chat. Existing workflow input waits also do not resume dependent nodes. The
workflow phase must provide an existing owned-chat binding or complete durable
chat provisioning, plus explicit browser handoff/resumption; current delivery
does not claim workflow support.


### Confirmed web acceptance and billing audit, 28 October

The final real manual-sign-in suite passed both desktop (1280 px) and phone
(390 px) with no retries. It exercised contextual consent, owner-only private
input, the same browser and original 250-credit cap on AI continuation, Secure
Area JSON, and owner close. Both final sessions settled without pending
accounting: 14 Browse credits on desktop and 13 on phone. The first viewer
frames took 1.731 and 1.805 seconds respectively. These are viewer-open
measurements after initial execution, not initial task startup. Recordings and
representative consent/result screenshots were reviewed; selected recordings
were uploaded privately with 48-hour links.

The current-schema Example Domain CLI run (`588bd4b4`) genuinely completed
in 17.514 seconds, with 2.336 seconds provisioning, 3.988 seconds initial
navigation and 1.274 seconds of observation RPC time. Its `startup_seconds`
was 7.152. Important correction: that timer stops **before** the first observe
RPC. Earlier prose calling the startup timer “first observation” was inaccurate.
The sum of those two latest measurements is at least 8.426 seconds; it excludes
any iteration bookkeeping between them. New instrumentation explicitly measures
startup through completion of the first observation, and separately records
pool claim, resume, pristine readiness and initial control. A redundant initial
control RPC on the verified fresh-pool path is removed under the same exclusive
lease; its improvement is not yet measured. No destination/privacy checks were
removed.

This extraction accrued five credits at completion. Leaving its compute running
through the existing idle grace and then closing it settled at 16 Browse
credits; the ten-credit assistant response makes 26 credits ($0.026) in total.
The final public example uses this current-schema result rather than the older
extraction, whose saved envelope predates `data_json`. The two public-example
price labels use complete account/chat ledger totals. For the two single-turn
source chats only, otherwise unlinked Browse rows are attributed to the sole
AI usage trigger without changing amounts or the real transcript. New Browse
settlements now retain their reservation's triggering message ID so future
response-level pricing can join normally.

Billing is by elapsed resource seconds, not minute blocks. For the verified
2-vCPU/4-GiB allocation, supplier compute is `2 × $0.000014 + 4 × $0.0000045 =
$0.000046/second`; the 2× customer compute rate is 0.092 credits/second or
5.52 credits/minute. Native internal model usage is added at 2× its effective
supplier tariff. Existing wallet policy floors accumulated credits with a
one-credit minimum for positive sub-credit usage; it does not impose a
per-click or per-minute minimum. Confirmed paused time adds zero. Six added
checks cover 1, 17, 59, 60, 61 and 90.5 elapsed seconds plus paused retention.
The Browse listing previously advertised a zero fixed fee; the prepared
correction preserves the fractional display rate and does not add a generic
dispatch charge.

Rates were rechecked against [E2B pricing](https://e2b.dev/pricing) and
[billing documentation](https://docs.e2b.dev/billing). One lifecycle accounting
assumption still needs investigation: local running-cost estimates cap at the
planned provider deadline, while E2B documents a potential delayed auto-pause
during snapshot backlog. A planned deadline is not always the actual stop
event. Do not claim invoice-exact reconciliation for that edge case; retain
separate measured supplier estimates and settled customer credits.

The user explicitly clarified that standalone and workflow Browse must not
require a chat. The recommended core authority is owner + execution scope +
idempotent operation, with owner-encrypted results, lifecycle and billing
independent of delivery. Chat embeds and workflow run views are adapters.
Workflow handoff must use its own run/node occurrence and a resumable wait,
not a fabricated chat or an unpersisted report-delivery ID. That refactor and
durable workflow resume are not yet implemented.


### Jev reference review

Rechecked [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast),
its [MIT license](https://github.com/browser-use/jev-ultrafast/blob/main/LICENSE),
[source loop](https://github.com/browser-use/jev-ultrafast/blob/main/jev_ultrafast/agent.py)
and [measurement boundaries](https://github.com/browser-use/jev-ultrafast/blob/main/docs/performance.md).
Its 7.073-second demo excludes browser setup, initial navigation and initial
observation, plus final independent verification. It cannot be compared directly
with our startup/first-page timer. The optimized upstream loop uses structured
DOM state without screenshots by default, a persistent browser session, one
atomic snapshot and a single speculative operation/target decision request.
It also uses event-aware settling and preserves generated text only for an
identical field context. These are useful implementation patterns, not evidence
of OpenMates speed or reliability. No upstream code was copied in this review.

OpenMates already uses direct Jev 1.14 typed operation/target selection, with
bounded generation/extraction through the separate text helper and independent
completion checks. Earlier measured Jev calls were 0.170–0.224 seconds. Runtime
screenshots/DOM observations precede the model call; local browser/network
overhead must be measured separately from Jev inference. Follow-up optimizations
should compare atomic snapshots, screenshot demand/cadence, connection reuse and
state-aware settling while retaining isolation, fresh targets and secret masking.


Additional source comparison found that our runtime already has atomic DOM
capture, viewport text bounds, retained node identities and occlusion checks.
The next meaningful Jev-loop improvements are stronger target/form/document
freshness guards, fuller HTML/ARIA label recognition, bounded event-aware
autocomplete settling, and reuse of a text result only when the complete helper
context is unchanged and no input outcome is uncertain. Upstream's focus
emulation addresses background desktop tabs; no evidence yet makes it relevant
to our dedicated headless VM. These are proposed changes, not deployed or
benchmarked improvements.


## Latest deployed status: 00c1f01, 28 October

The release is deployed to dev, its frontend is ready, and coordinated operation
`docker-ac003ce2` completed with all 17 affected services healthy. Backend source
and translation mounts were refreshed without rebuilding images. The operation
took 163.077 seconds, including 6.609 seconds Compose and 82.587 seconds health
checks; this engineering deployment duration is not browser startup latency.

The corrected public catalog API check and existing first-party authorization
case both passed isolated run `40683662151` against candidate `212cbca1`. The
first API attempt incorrectly requested the protected developer metadata URL;
its 401 was correct. The corrected test uses the public `/details` catalog path,
without changing authentication. Backend run `40681944353` passed the focused
service, dispatch and metadata checks.

All four new Browse catalog cases passed run `40681954302`: two actual CLI
examples at 1280 and 390 pixels, each displaying saved JPEG/JSON without any
owner-session request or live control. The full catalog suite had 11 passes,
six failures in other catalog/settings/audio cases and one skip; it is not
reported as fully green. The existing clone-on-send spec is held by the CI
coverage registry because its original scenario requires live inference; no
provider credential was added to CI or scenario replaced with a mock.

After deployment, all four logged-out example-page checks passed: the SEO page,
real transcript, screenshot preview, fullscreen, readable JSON, close and reload.
Screenshots were reviewed on laptop and phone, and no owner browser endpoint was
contacted. Verified pages:

- https://app.dev.openmates.org/example/browse-example-domain
- https://app.dev.openmates.org/example/browse-heading-json

A fresh automatically routed CLI extraction, chat `9a56b812`, verified the exact
deployed backend source under a shared runtime lease and completed Browse with
JSON. Its new stage instrumentation measured:

| Stage | Seconds |
| --- | ---: |
| Prepared-pool claim | 0.190 |
| Native resume and readiness | 1.869 |
| Owner/pristine control check | 1.063 |
| Provisioning, including the above and persistence | 3.182 |
| Initial navigation RPC | 4.180 |
| Duplicate initial control RPC | 0.000 |
| Startup before observation | 7.449 |
| Observation RPC | 1.258 |
| Startup through first observation | 8.744 |
| Entire Browse execution | 18.175 |
| Outer assistant/CLI response | 49.819 |

Provisioning is below four seconds but not consistently below three; the first
page observation remains substantially too slow. The navigation RPC still
combines destination/robots work with page loading. Further measurements must
split that work and connection setup before claiming a root cause. Removing
one duplicate control round trip did not materially improve this total.

At task completion, supplier estimates were $0.0036007768 total: $0.0007739159
runtime and $0.0028268640 internal inference. Accrual was seven credits. The
script closed its browser immediately after the outer response and embed read,
settling at nine Browse credits with no pending accounting. The ledger contains
exactly one Browse and one assistant entry, with ten assistant credits: 19
credits ($0.019) total. The new Browse billing trigger matches the assistant's
trigger, the ledger matches the close receipt, and the original 40-credit cap is
preserved. No per-minute rounding is involved. The longer-lived final sign-in
checks cost 45 credits (14 Browse + 31 assistant) on desktop and 40 credits
(13 Browse + 27 assistant) on phone. These are measured examples, not a general
price or reliability guarantee.

Remaining work is deeper navigation/transport profiling, qualification beyond
these permitted fixtures, supplier pause-deadline reconciliation, and the
chat-independent execution/workflow refactor. Code Run already provides the
standalone route/shared admission/optional chat-delivery precedent. Keep Browse's
stronger deterministic admission and owner-encrypted stores; do not copy Code
Run's non-idempotent random start IDs or broaden browser credentials to generic
developer keys. Workflow takeover belongs in the workflow run view, with durable
node continuation that preserves completed upstream effects. Together/DeepSeek
remains unqualified while its organization ZDR flag is false; measured text
helper runs used the Gemini fallback. Rust parity remains explicitly deferred.


## Connection profiling release: 56005ce

The timing-only transport patch passed 88 isolated backend checks in run
`40688496181` (candidate `df280c8f`) and is published as `56005ce`. HTTPX trace
callbacks retain only an allowlisted set of numeric TCP/DNS, TLS, response-header,
response-body and total durations. Request/response objects, URLs, headers and
exception details are discarded; locally generated measurements override any
remote `_rpc_timings` field. Both HTTP/1.1 and HTTP/2 traces are covered by the
privacy regression test. Navigation and first observation expose these numeric
stage durations without changing connection/retry/authorization behavior.

Further optimization should test owner/session-scoped persistent connections and
fewer RPC round trips, retaining all ownership, pristine-browser, robots and
fresh-target checks. The runtime currently closes its HTTP/1.1 connection after
every RPC, and the backend creates a fresh client for every operation. These are
observed implementation facts, not a measured causal explanation yet. Runtime
protocol changes require rebuilding and qualifying the immutable prepared E2B
template, rather than merely restarting backend services.

[E2B's current region documentation](https://docs.e2b.dev/faq/egress-ip-ranges)
lists US West as the default and an EU region enabled through support. Confirm
this workspace's actual placement before attributing latency to distance. EU
placement is a potential experiment within the preferred E2B infrastructure;
no region migration or support message has been performed.


### Live transport trace and direct-runtime comparison

Coordinated development operation `docker-51c841d6` completed with all targeted
services healthy. It took 584.242 seconds, dominated by 485.609 seconds waiting
for other authorized development work. Compose took 4.390 seconds and health
checks 33.657 seconds. This is engineering deployment time, not browser startup.
A subsequent paid extraction held the shared runtime lease and verified all
nine owned backend files against release `56005ce` before calling inference.

Automatically routed chat `ebbe08ec` completed with verified JSON. Browser
`543959b1` was closed in the script's finally path, with eight settled Browse
credits and no pending accounting. An independent owner usage read confirmed
exactly two ledger entries, eight Browse plus eleven assistant credits (19 total,
$0.019), matching the close receipt and billing trigger. The original 40-credit
session cap remained intact. This is another measured example, not a flat fee.

| Stage | Seconds |
| --- | ---: |
| Pool claim | 0.203 |
| Resume/readiness | 1.918 |
| Pristine control check | 1.567 |
| Provisioning | 3.747 |
| Navigation TCP/DNS | 0.0170 |
| Navigation TLS | 0.0090 |
| Navigation response-header wait | 4.5030 |
| Navigation RPC total | 4.5420 |
| First observation response-header wait | 1.0970 |
| First observation response-body transfer | 0.1740 |
| First observation RPC total | 1.3390 |
| Startup through first observation | 9.749 |
| Entire Browse execution | 17.765 |
| Outer assistant/CLI response | 48.210 |

TCP/TLS connection establishment is not the main bottleneck in this sample.
The response-header interval still includes E2B forwarding, browser/controller
work, crawler-policy checking and destination loading; it does not isolate them.
A fast edge handshake also does not exclude distance in E2B's internal forwarding.
The page-ready target remains unmet. Connection reuse alone is not a supported
solution to this result.

A separate inference-free provider diagnostic created an empty isolated browser,
read public Example Domain and compared fixed operations remotely and through
localhost inside that same VM. It destroyed the VM in finally. Remote metadata
requests took 0.2180 and 0.7064 seconds, versus 0.0081 and 0.0008 locally. Remote
observations took 1.2646 and 1.0171 seconds; local observations took 0.4849 and
0.0255 seconds. Remote navigation took 3.8279 seconds, of which 3.7601 was waiting
for headers. Only durations and response-byte counts were printed, with no page
contents, control secrets or provider handles.

This small sequential comparison is not an alternating benchmark; cache and
screenshot warmup can affect observations. It nevertheless establishes that a
nearly immediate local metadata operation can have material remote overhead.
The next bounded optimization should combine native-resume readiness with the
required live pristine/control verification in one authenticated request. It
must still persist the paid handle first, prove Chromium readiness and blank
storage, and destroy a rejected handoff. Ordinary existing-session resume must
retain its controller-safe read-only readiness behavior. Combining navigation
with its first observation can remove another round trip, but requires a new
runtime/template and direct isolation/privacy qualification. Measure crawler
policy and browser navigation separately before changing navigation waits.
