# Mercury 3 authorized rollout addendum — 2026-10-20

**Status: deployed to dev in `7ff9714f24c62a0b8bc5d07e164b7b719be055b7`;
frontend ready and coordinated backend services healthy.** After reviewing the expanded
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

The rollout implements customer cache savings on native Inception
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
outputs and sixteen workflow plans per arm were insufficient for rollout confidence;
the broader correction/workflow coverage below subsequently completed. Bounded writing
still exposed unsupported claims. These small samples and the absence of a
matched independent Mercury/Gemini public general-quality comparison support
retaining Gemini for medium complexity. See the cited
[public benchmark review](public-benchmarks.md).

The original correction-only dev deployment and facade proofs remain valid
historical evidence. They do not verify the new Gemini 3.8 fallback, active
workflow routing or low-complexity default routing. The new phase's evidence and
its native recovery limitation are recorded below.

## Completed verification and receipts

Expanded correction and workflow comparisons each completed 96 rows, followed by
48 Mercury LOW workflow diagnostic rows. Correction manual fidelity passed 46/48
Mercury versus 45/48 Gemini. Workflow INSTANT had six critical/incomplete results
and two unresolved relevance gaps; LOW diagnosis had one critical incomplete
result and one unresolved gap. These defects remain material. The user authorized
the bounded rollout after reviewing them; Flash-Lite postprocessing remains.

The exact routing@7 and workflows@12 contracts were presented and approved, with
fingerprints `f3e3e6061a2480b959d503227867af0d51de35c5142ca23fe7b176129a5e5a42`
and `f6d44179471229ac1c90915e7a7694e759af0c35fc6fea9ce7537a60e9117021`.
The review and approval artifacts remain under `/tmp/openmates/specification-approvals/`.

| Required behavior | Evidence | Result and scope |
| --- | --- | --- |
| Low default, outage fallback, manual selection and disabled restrictions | `mercury3-model-picker.spec.ts`, CI 39429825856, source `9d24dae5c3c64a6d36c402c0acd88c03b49e6e4e` | 2 passed, no skips/flakes. Disabled scenario used only Gemini, zero Mercury provider attempts. Focused tests cover keys, modalities, saved preferences and first-substantive deadlines. |
| Correction, insertion and fallback | `audio-recording.spec.ts`, CI 39425522674, source `093d4c77520f49ca41f0cb10db9cd082a8971258` | 15 passed; identical backend and web/UI product trees to `9d24dae5`, later changes were test readiness only. |
| Workflow repair, retained prefix, partial notice, Stop and Undo | `workflows-input-stream.spec.ts`, CI 39429832028, source `9d24dae5` | 2 passed, no skips/flakes. |
| Actual persistence/reload, repair/exhaustion/outage and billing | `workflows-authoring-transaction.spec.ts`, CI 39422083638, source `efbe680fc98c96dcf7fb28f9322f054aeda22d2c` | 2 passed against private Directus; external inference mocked. Backend tree identical to later pre-merge browser candidate. Nonvisual setup proof exemption. |
| Adapters, deadlines, Jev, routing and actual-attempt/cache billing | Focused local backend and frontend suites | 390 backend checks across selected suite and added credential-deadline case, 32 sender/restriction tests; additional workflow/parser and benchmark checks passed. |
| Published composition | Reviewed candidate `5ef898d246ec19c9130fa918c36af803fa98d175`, base `f23144e82e393e09a7309b8699837059a83938ac` | All 56 deployed paths match exactly. 53 owned paths equal CI `9d24dae5`; remaining changes preserve unrelated upstream tool-source metadata, manifest entries and generated indexes. Independent review found no conflict; all 75 merged routing/source-contract checks passed. Earlier CI is scoped evidence, not execution of the final merged SHA. |
| Dev readiness | Publication `7ff9714f24c62a0b8bc5d07e164b7b719be055b7`, runtime `docker-bf0dee84`, frontend wait-deploy | API and expanded backend consumers healthy; runtime revision matches publication; frontend deployment succeeded. Production unchanged. |

The per-turn `model_routing_restrictions` snapshot carries only disabled
model/server lists through fast admission and regular send paths. Backend
validation applies it to the current request without changing stored preferences.
Healthy Jev, Unsure behavior, medium defaults and Flash-Lite postprocessing stay
unchanged. Six latest-success browser recordings were uploaded; no selected
capture or upload failed. Private signed evidence URLs are not committed here.

## Native runtime outcome and quality limit

The deployed nonstreaming correction facade passed all six original synthetic
cases once, including German/mixed language, names, numbers, negation and quoted
instructions. All used Mercury without fallback: median **1.135 s**, range
**0.541–2.693 s**, no skipped cases. Loaded modules, enabled gate and published
bytes were verified, without environment/model overrides or runtime mutation.

A separate German two-city weather test injected an invalid INSTANT Ask AI node
after two accepted weather nodes, then used real native **Mercury LOW → Gemini
3.8 LOW**. Both suppliers returned HTTP 200. Mercury repeated the forbidden
`capability` field; Gemini produced a valid typed-reference comparison but omitted
the final Send. Its strict complete-workflow oracle **failed** and that failed
receipt remains preserved. No prompt/oracle tuning or additional live attempts
were used to hide the result. The planned subsequent controlled-prefix scenario
did not run because this strict check stopped the runner; equivalent exhaustion
and immutable-header behavior is covered by focused and real-database checks.

The requested failure policy **passed**: exactly three author attempts (one
controlled INSTANT and two native repairs), original nodes/edges unchanged, no
duplicate callbacks, and a validated **disabled partial** with the specific
notice and manual-edit guidance. Total time was 6.050 seconds. The probe wrote no
user workflow and had no billing context; billing is verified separately by
unit/database tests. This native example proves bounded safe failure, **not full
recovery**. Deterministic successful repairs do not guarantee every live mistake
can be repaired. These results support retaining Gemini for medium complexity.

Private source-bound receipts are retained in
`logs/mercury-fast-inference/acad-2026-10-20/`: correction report/runtime/runner,
`live-workflow-recovery` raw report/archive and a separate adjudication preserving
the failed completion result. The CI summary and inventories retain actual
source/run/cleanup identities and the selected latest-success recordings.

The [Plan](plan.yml) is verified for the authorized dev rollout and bounded
failure policy. Expanded/native quality defects remain disclosed. Production,
paid-capacity changes and medium-default changes are outside this completion.
