# Browse qualification — 26 October 2026

Backend qualification is in progress. These are development measurements, not a
claim that web embeds, workflow support or general browsing acceptance are complete.
The approved contract is `feature.app-skill.web-browse@1`.

## Environment and scope

E2B hosts Chromium in a prepared Playwright 1.64.1 image with 2 vCPU and 4 GiB RAM.
The prepared browser path must also be passed in the sandbox runtime environment:
E2B template environment variables apply during the image build only.
The live assistant test uses automatic routing. Browse itself uses Jev 1.14;
the text/extraction calls used Gemini 3.8 Flash. Together's verified organization
retention flag remains disabled, so these results do not qualify the DeepSeek primary.

Tests use an isolated CLI profile, disposable Project and temporary SDK key with
a daily credit limit and expiry. No account defaults or model overrides were changed.

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
- A 125-second native idle probe confirmed auto-pause, then reproduced HTTP 502 on
  the first browser RPC after successful resume. The current candidate waits on
  bounded metadata-only readiness checks and never retries an input action.
- Mouse-driven navigation can invalidate an observation's execution context.
  The current candidate retries that read at most three times after document
  readiness; access denials and a closed original page are not retried.
- The text helper returned a grounded but abbreviated purpose statement. Native
  completion scored it 0.84, below the unchanged 0.95 threshold; a complete
  statement retaining the page's relevant caveat scored 0.95 and an invented
  banking claim scored 0.0. Extraction now preserves relevant qualifications,
  and controller instructions distinguish answer formatting from website actions.

The retained real session recovered its interrupted settlement and reported 12
charged credits. Its subsequent browser resume still failed before readiness;
it is not a successful reuse case. The CLI's next run dispatched Browse, returned
a failed Browse result and recovered through `web.read`. That is a Browse failure
despite the CLI process exiting successfully.

The deployed dispatch, settlement and pause-recovery change passed 32 focused
tests locally and in isolated CI (run 40336127998). The preceding broader backend
and Google SDK check passed 88 tests. The readiness/observation candidate passed
61 focused local tests before five additional transport cases, which also passed.
Native provider probes are additional evidence;
they do not replace CLI, SDK or web acceptance.

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

## Remaining acceptance

Successful CLI and npm/Python JSON delivery, final settlement and idempotent retry
are being verified. Rust parity is unavailable until the separate Rust migration
lands or the user explicitly defers that phase prerequisite. Web screenshot embeds,
watch/takeover/private sign-in/continuation and laptop/mobile proof follow the CLI
and required SDK gate. Workflow verification follows the regular skill and embeds.
