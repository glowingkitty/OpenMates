# Mercury 3 authorized rollout addendum — 2026-10-20

**Status: user-approved implementation, testing and scoped dev deployment;
publication and verification receipts pending.** After reviewing the expanded
results, the user explicitly instructed implementation and deployment of Mercury
transcript correction, eligible low-complexity defaults and the bounded workflow
recovery chain below. The earlier readiness hold is superseded by this decision;
its quality findings remain evidence, not resolved defects. The parent records
the updated exact workflow contract review and approval receipt. Historical
[evaluation](evaluation-2026-10-20.md) and expanded reports remain unchanged.

## User-approved implementation policy

- **Ordinary transcript correction:** native Mercury 3 **LOW** primary, with a
  five-second deadline and native Gemini 3.8 Flash **LOW** fallback. Upgrade the
  older Gemini 3.5 fallback. Preserve meaning, original transcript timestamps,
  actual-model attribution and existing correction failure behavior.
- **Workflow authoring:** at most **three actual author calls per request**:
  native Mercury 3 **INSTANT → Mercury 3 LOW → Gemini 3.8 Flash LOW** across
  initial generation and validation repair. Mercury timeout/outage skips the
  unavailable route; an early outage may use Gemini LOW plus one Gemini LOW
  repair, still within three calls. Stop never advances. Preserve accepted
  prefixes, actual-attempt billing and Jev decisions. If repair fails or cannot
  safely replace a semantically wrong accepted prefix, retain a disabled partial
  with specific information and manual-edit guidance; do not claim every mistake
  is recoverable. Mercury deadlines are five seconds for credentials/first useful
  output, five idle seconds and fifteen seconds total per call.
- **Low-complexity text:** native Mercury 3 **LOW** default on eligible requests,
  with native Gemini 3.8 Flash **LOW** fallback after five seconds without the
  first substantive answer. Preserve exact model preferences and global account
  settings. Unsupported vision and other Mercury-ineligible requests use Gemini.
- **Preprocessing/routing recovery:** Jev remains primary. Only where the
  existing decision contracts allow generative recovery, use Mercury 3 first
  and Gemini 3.5 Flash-Lite second. Preserve Unsure handling; healthy Jev does
  not invoke generative recovery. This does not replace the Gemini 3.8 Flash
  LOW fallbacks for the three product flows above.
- **Medium complexity:** leave the Gemini default unchanged. Product Mercury
  routing stays direct Inception; OpenRouter remains synthetic-benchmark-only.
  Production rollout is outside this dev authorization.

The account owner already confirmed that “Improve the model for everyone” is
OFF for the direct Inception account. This account-specific training opt-out
is distinct from retention; no unconditional zero-retention claim is made.
The temporary 50% launch discount remains shared with customers: **3,300 input /
950 output tokens per credit**, compared with regular **1,650 / 475**. No
published promotion expiry was established.

## Caching verified separately

Direct Inception [official FAQ](https://docs.inceptionlabs.ai/resources/faq)
specifies automatic prefix caching without an activation parameter. Cache
hits are reported in `usage.prompt_tokens_details.cached_tokens` within total
prompt tokens. No minimum prefix length or TTL was established from the reviewed
docs; no cache pin/invalidate/inspect API is documented. The
[official price table](https://docs.inceptionlabs.ai/get-started/models) lists
supplier cached input at $0.01/M during launch, versus ordinary $0.10/M.

The pending rollout implements customer cache savings on native Inception
chat and workflow settlement through the shared category calculator. Reported
cached input receives **33,000 tokens/credit promotional / 16,500 regular**;
ordinary input remains **3,300 / 1,650** and output **950 / 475**. Included-input
write billing adds no separate cache-fill fee. Missing counters retain ordinary
inclusive-input billing; invalid cached subsets fail closed. Minimum charges and
rounding mean the cached-input discount is not 90% off every complete bill.

The cache policy's November 20, 2026 expiry is an internal evidence-review
deadline, not a documented provider cache TTL or launch-promotion expiry.
Workflow supplier USD estimates remain conservative ordinary-input estimates,
not cache-adjusted invoices. Existing postprocessing receipts show 80,018/94,356
Mercury input tokens cached (84.8%), positive hits on 20/20 calls; these calls do
not establish cache minimums or TTL. No additional calls were needed.
[Provider caching/accounting details](../../apis/inception.md#automatic-prefix-caching).

The separate [native postprocessing comparison](postprocessing-2026-10-20.md)
supports keeping Gemini 3.5 Flash-Lite for that generative postprocessing task:
medians 1.603 s Lite versus 1.590 s Mercury LOW, with Mercury language and
output-contract defects. It does not alter the approved three Mercury-primary
flows or Jev's primary decision role.


## Evidence and limits

The completed native [evaluation](evaluation-2026-10-20.md) identifies candidate
settings by task: Mercury low preserved meaning in 12/12 transcript outputs;
instant produced 16/16 valid, intent-matching workflow plans. Twelve transcript
outputs and sixteen workflow plans per arm are insufficient for rollout confidence.
Broader transcript correction and workflow quality coverage must come first. Bounded writing
still exposed unsupported claims. These small samples and the absence of a
matched independent Mercury/Gemini public general-quality comparison support
retaining Gemini for medium complexity. See the cited
[public benchmark review](public-benchmarks.md).

The original correction-only dev deployment and facade proofs remain valid
historical evidence. They do not verify the new Gemini 3.8 fallback, active
workflow routing or low-complexity default routing. No new deployment, CI result
or runtime outcome is claimed by this addendum.

## Remaining verification and receipts

Expanded correction and workflow comparisons each completed 96 rows; the later
Mercury LOW workflow diagnostic completed 48 more. See
[expanded correction](expanded-correction-2026-10-20.md) and
[expanded workflow, including LOW diagnosis](expanded-workflow-2026-10-20.md#later-diagnostic-mercury-low-same-frozen-selections).
Correction manual fidelity passed 46/48 Mercury versus 45/48 Gemini. Workflow
INSTANT had six critical/incomplete results and two unresolved relevance gaps;
LOW diagnosis had one critical incomplete result and one unresolved gap. LOW
improved observed defects but independent arms do not test the chained recovery
policy. These defects remain material. Preserve Flash-Lite postprocessing.
Parent records final source
revision, focused checks, isolated CI evidence,
scoped dev publication and runtime verification. Required behavior includes
first-substantive timing, failure/fallback outcomes, exact-preference and modality
eligibility, accepted-prefix preservation, actual-attempt model attribution and
billing, plus unchanged Jev and medium-complexity routing. Verify healthy Jev
never invokes generative recovery and eligible recovery uses Mercury before
Gemini 3.5 Flash-Lite without weakening Unsure contracts. Pending:

A routing audit found a separate adoption gate: disabled model/server settings
are intended processing restrictions (`userProfile.ts:53–57`), but
`message_received_handler.py:2555` onward does not forward them to the backend.
Candidate backend guards enforce these restrictions only when supplied. This
transport gap predates Mercury, but new automatic Mercury routing cannot ship
while inheriting the bypass. The user now explicitly requires this restriction transport fix and verification
as part of implementation before automatic rollout. Parent and source workers
own those edits; this documentation change does not implement them.

- Expanded quality evidence: **complete; defects disclosed; user authorized implementation after review**.
- Exact updated workflow contract review/approval receipt: **pending parent**.
- Disabled-model/server restriction transport and enforcement: **pending; blocks automatic rollout**.
- Final source and scoped dev publication: **pending**.
- Focused checks and isolated CI evidence: **pending**.
- Shared runtime verification and final rollout receipt: **pending**.

The [Plan](plan.yml) remains schema-valid `implementing`, with its evidence phase
marked user-approved implementation, until these checks and receipts are complete. Source/configuration and Specifications are owned by the parent and
implementation workers; this addendum records the approved policy only.
