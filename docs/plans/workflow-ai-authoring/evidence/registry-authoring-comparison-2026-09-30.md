# Registry-driven workflow authoring comparison — 2026-09-30

## Latest deployed state

The generic pipeline and immediate fullscreen streaming are deployed at
`607cd834`; authoring billing and EUR shopping guidance are deployed at
`127f161f`. The focused web stream and Billing settings cases passed isolated
CI. The final live shopping proof passed intent, 13-credit debit, history and
idempotent replay checks. See [exact diverse requests and results](diverse-workflow-authoring-2026-09-30.md).
The comparison and trial records below describe their historical revisions;
their pending checks are not statements about the latest deployment.

## Historical compact-plan trial and implementation state

The authoring prototype uses registry-derived Jev skill and mode preselection,
Gemini 3.8 Flash to author a compact semantic plan, and a backend compiler to
produce and validate V2. The task workspace contains its generic workspace and
chat integration, provisional component stream, and atomic queued save path.
The accepted per-node validation and partial-save contract still needs
integrated verification, durable acknowledgement timing and product rollout
checks. Live synthetic inference on deployed API revisions does not establish
a working released path.

### Exact-source Jev selection comparison

At deployed revision `68cdee7984774de384ece75778fcf4eb4e0ddbec`, the same
seven synthetic requests were each run once with direct skill selection and
once with Jev selecting apps first, then app skills in parallel for those apps.
Both modes used the same Gemini author and V2 compiler source. This paired
one-sample comparison informs further work; it does not establish a causal
quality or latency winner.

| Jev route | V2-valid | Intent checks | Required-skill recall | Extra skills | Median Jev | Median total | Median first header incl. Jev | Median first action incl. Jev | Actions under 2 s | Estimated total cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct skill selection | 6/7 | 4/7 | 100% | 10 | 351 ms | 2.375 s | 1.878 s | 2.063 s | 3/7 | $0.031747, incomplete |
| App first, parallel per-app skills | 7/7 | 6/7 | 100% | 10 | 650 ms | 2.546 s | 1.954 s | 2.189 s | 0/7 | $0.032562, complete estimate |

Direct selection missed the weekly weather schedule time because the authored
plan used an incorrect `at` value; the time handling fix is pending retest.
Both modes added an unrequested Ask AI step in the subjective AI-check case,
which would add runtime cost. Direct selection's events case had a provider
generation failure after one complete action callback, so its graph and
intent scores failed and its provider usage estimate is incomplete. Staged
selection passed those events checks in its one attempt. These differing
outcomes mix model sampling and route effects; the table alone cannot assign
the cause.

The report's `generation_metrics.first_component_ms` marks Gemini's first
header. Its `first_complete_component_ms` callback marks the first authored
action node. The table adds each case's Jev selection time before taking the
median, so these are elapsed times from preselection start to header or first
action callback. The report's after-generation first-action medians are
1.726 s direct and 1.505 s staged; those exclude Jev. Neither callback
measures UI delivery or proves that the action was validated before display.
Complete-request
timing includes Jev, Gemini, compilation and the bounded intent oracle, but
excludes persistence, durable queue acknowledgement, UI delivery and workflow
execution. Cost totals are estimates from reported token usage, not invoices;
the direct total lacks complete usage for its failed events generation. The
full plans and case diagnostics remain private at
`/tmp/workflow-staged-flat-fixed-comparison-20260930.json`. Source SHA-256
values for preselection, Gemini authoring, compiler and comparison harness
are recorded in that report.

The next targeted six-attempt live run on deployed `9ee121bb26863a63c0e003936bbbf18fe39beacb`
passed both subjective AI-check attempts; direct and staged weather plus
direct and staged events failed at provider generation (2/6 graph-valid and
intent-matching). The wrong weekly `at` value now has an actionable error and
schema-field descriptions are fixed in the task workspace. A full live retry
is pending. This targeted sample does not supersede the paired seven-case
scores; it isolates the remaining failures. Its private report is
`/tmp/workflow-flat-quality-targeted-20260930.json`.

Focused isolated CI passed for CLI file coverage (`36756996852`), authoring
transaction (`36757002613`), workflow input (`36757013549`), and streaming
(`8f58abce`, run `36759901975`, source `ace9b682`). The earlier backend
revision `1448b264` was healthy on dev, and web revision `cc4e802` completed
Vercel deployment. The first three
isolated runs tested candidate source `7d95d5e`
with harness `68cdee`; the stream run tested `ace9b682` with harness
`cb431abd`. The transaction run covered one two-target commit and guarded
rollback case. The input run's long single/New case also covered editor
preview and rejection, saved summary, added and edited highlights, Undo
conflict and success, dirty Save/Discard/Stay, and landing-page edit; its
second case covered corrected voice submission and the `correction.failed`
branch, which displayed the raw transcript without submitting it. The input
test and workflow page files are identical between CI source `7d95d5e` and
deployed web `cc4e802`, so this browser behavior has source-matched coverage.
The stream run's long case
covered rejected streams, disconnect recovery, single-open and multiple-New
navigation, validated node preview, retry phase, Stop, and the partial-result
warning. Focused checks separately passed 32 workflow-input helpers, 12 chat
checks at backend gate `729`, 54 then-current planner/compiler/provider checks at
backend subject `658a872`, eight earlier preselection checks, and eight Node
transaction proof checks plus a prior transaction suite. These scoped checks
and deployments do not prove the full Plan assertions or live authoring.

The first paid CLI short-default attempt failed before a workflow header was
emitted on two attempts, after 6.67 seconds of planner time. It saved no
workflow or other state. Estimated provider cost was $0.00997465 with
incomplete usage, so it is not a billing receipt or successful delivery cost.
The later bounded short-default retry (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-5a2238b9.json`)
completed one workflow. Its first header appeared at 3.85 seconds, first
validated action at 3.94 seconds, and final SSE event at 4.5 seconds; planner
time was 3.128 seconds. Estimated complete provider cost was $0.00662519,
not an invoice. These stream timings do not establish durable acknowledgement
latency or performance across requests.

The spoken-correction run (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-d5144a26.json`)
created a disabled workflow after one Gemini generation. Its Thursday 09:00
schedule and Lisbon web search were correct, but the schedule timezone was UTC
instead of the requested Europe/Lisbon; the report therefore failed its
assertion. Planner time was 2.162 seconds, service time 3.905 seconds, CLI
wall time 4.597 seconds, and estimated complete provider cost $0.00623082.
The Jev timezone-selection fix passed a spoken-correction rerun on backend
`1448b264` (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-b58393c4.json`):
Jev selected Europe/Lisbon in the same call and the disabled workflow saved
Thursday 09:00 in that timezone with the requested Lisbon events search after
one Gemini generation. CLI wall time was 9.002 seconds, planner 6.635 seconds,
service 8.257 seconds, Jev 0.407 seconds, and Gemini 6.123 seconds. The first
provider component/header arrived at 5.6667 seconds. Estimated complete
provider cost was $0.00672908, not an invoice. The difference from the earlier
4.597-second faulty run is one-sample provider latency variation; it does not
establish a persistent performance regression. A cache lookup optimization
measured about 52 ms before and 2 ms when warm, outside these end-to-end
comparisons. Focused selector/planner/compiler/provider checks passed 88 cases
at backend `1448b264`.

The initial schedule-edit structural case (`ff6dc3cb`) executed in 4.378
seconds CLI wall time and 2.203 seconds planner time, with estimated complete
provider cost $0.00406514. The encrypted durable before/after state showed
only the trigger changed. The apparent baseline mismatch was traced to an API
alias serialization bug, fixed in deployed backend `be2e5ebe`.

The next structural run (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-5feda643.json`)
passed its strict schedule-only edit: CLI 5.280 seconds, planner 2.276 seconds,
service 4.628 seconds, estimated complete provider cost $0.00457514. Its
app-parameter edit failed `node_selected_schema` on both Gemini attempts,
saved no workflow, and reported CLI 5.436 seconds, planner 3.876 seconds,
service 4.850 seconds, and $0.00879007 estimated cost with incomplete usage.
The report's overall structural verdict was therefore failed. Source review
found a date-field marker gap in registry metadata and compatibility gaps for
untouched legacy Send text and labels; the exact rejected Gemini node was not
retained, so these are source-based diagnoses rather than proof of that node's
specific failure. A scoped compatibility patch added generic date markers,
optional message-block labels, ID-only reuse for already selected enabled
App, Ask AI, and Send nodes under strict updates, full ordered-graph validation,
and rejection of incomplete Send fields before streaming. Check ID reuse and
sparse patch mode remain outside this patch. The patch was deployed as
`d25b19389d00084acd64a7b9b89ef52427fed9ce`; coordinated API rebuild
`docker-d8abb7a1` completed healthy. The web revision `cc4e802` also has a
successful Vercel deployment. The later structural CLI report
`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-ca9da8d1.json`
reported five passing cases. Four supported cases passed on closer inspection:
a strict schedule edit preserved the rest of the graph; an app edit changed
only query and city; two creations committed together; and guarded Undo
returned a conflict while preserving a later manual edit. The unsupported
Slack case's original assertion only checked for the absence of Slack nodes.
Inspection of its saved session
(`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-ca9da8d1-invalid-session.json`)
showed that both partial workflows instead contained a schedule trigger and
`send_chat_message`: Slack was silently substituted with chat. The partial
save was triggered by an incidental Jev exact-check-mode omission, not by a
recognized unsupported operation. Both workflows stayed disabled, no
automation ran, and both were deleted. This case passed disabled-state safety
but failed user intent; the runner assertion was too weak. These are bounded
live structural results, not a broad quality score.
Focused checks passed 59 compiler/provider,
16 root planner, 22 selector, and 34 input cases, 131 total; normal model and
security gates also passed. Live acceptance and rollout verification remain
pending.

The natural Berlin weather case then failed its complete-quality assertion
(`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-4a51baa5.json`,
session `0eb130e1-9b78-4ee6-999c-4a2b4def3ed2`). Jev classified a clear
create request but selected AI check mode for the typed rain condition.
Gemini's first attempt failed `node_selected_schema`; its second yielded four
validated nodes before `check_mode_omitted`. The workflow remained a disabled
partial draft with Europe/Berlin correctly selected. CLI wall time was 5.799
seconds, planner 4.267 seconds, service 5.229 seconds, and estimated provider
cost $0.00875895 with incomplete usage. The preselector rule is being
corrected; complete weather behavior and rollout acceptance remain pending.
The task workspace also has Jev hints for unconditional schedules with 26
focused checks and a safer Stop metadata read with five focused checks.
Safety source `557ebc1b190c7cf39933aef04035714c7d6a2e80` has now been
deployed with Jev typed hints and check guidance, an unsupported-workflow
marker, safer node-kind diagnostics, and a lean Stop metadata read. Four
impacted pytest files passed normal gates. The marker rejects an unsupported
workflow before its header and preserves an earlier valid prefix when Gemini
emits it, but deterministic per-workflow channel enforcement is not yet
implemented. Coordinated API runtime `docker-10fdd6d9` is healthy. The natural
Berlin weather rerun (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-92d64fa2.json`)
passed its strict check in one Gemini attempt: a complete Berlin daily 08:00
today workflow with exact rain yes/no. CLI was 5.204 seconds, planner 2.802
seconds, service 4.514 seconds, and estimated complete provider cost
$0.00517570. The first Gemini component took 1.203 seconds from generation
start; that is not client first-preview timing. This is one bounded quality
case.

The unsupported-batch rerun (`/tmp/openmates-workflow-authoring-session3e12/workflow-rollout-6f0921dd.json`)
passed its strict intent and safety assertions: after `unsupported_operation`
on both Gemini attempts, exactly one disabled Monday chat prefix was saved;
there was no Friday or second workflow. CLI was 4.388 seconds, planner 2.800
seconds, service 3.809 seconds, and estimated provider cost $0.00368447. The
first Gemini component took 1.283 seconds from generation start; it is not
client first-preview timing. An initial cleanup 401 was recovered with isolated
login; exact nonce IDs were deleted, leaving zero test workflows. Both latest
live cases have now passed their final assertions and cleanup checks.

The latest accepted UI behavior prioritizes immediate visual feedback rather
than a generic two-second completion target. On create submission, a local
empty full-screen workflow shell appears before Jev, Gemini, or a validated
header, with a processing container above the first node. Validated title,
description, and nodes arrive one at a time. If Jev detects multiple workflows,
the view switches to the workspace batch view. The provisional shell does not
save an empty workflow, create a copy, or invent an ID; durable commit confirms
the real workflow. This behavior is deployed at `607cd834`; the single focused
browser stream case passed [CI run 36789254173](https://github.com/glowingkitty/OpenMates/actions/runs/36789254173).
The later `127f161f` deployment fixes EUR shopping intent and authoring billing.
Exact diverse requests, final debit/history/replay proof, timing boundaries and
remaining verification are recorded in [the diverse authoring report](diverse-workflow-authoring-2026-09-30.md).

### Earlier compact-plan trials

Before the paired comparison above, the same seven synthetic requests had four
live compact-plan runs.
Each result is a separate attempt, not an offline regrading of another run.
Provider prompts, schema handling, and bounded intent checks changed between
revisions, so a difference between rows is not a measured model improvement.

| Live run and source | V2-valid | Intent checks | Mean complete request | Mean first action callback, including Jev | Mean estimated USD per attempt |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial compact JSON trial | 6/7 | 6/7 | 2.543 s | 1.863 s | $0.004643 |
| First deployed retest, `42f5c5d` | 5/7 | 3/7 | 3.333 s | 2.858 s | Incomplete usage |
| Valid JSON retest, `63e2063` | 6/7 | 4/7 | 2.429 s | 1.941 s | $0.004652 |
| Bounded-schema retest, `865ab7b` | 3/7 | 3/7 | 2.975 s | Incomplete generation | Incomplete usage |

The initial failure was the three-city weather request: Jev omitted an
implied Ask AI capability needed to compose one message with forecasts and a
missing-forecast response. The compiler rejected the invalid selected-schema
step. In the first deployed retest, weather produced a graph but missed the
requested fallback and existence check; raw speech failed provider generation;
the shopping case was rejected for an icon value. The subsequent valid-JSON
retest passed weather and raw speech. It failed web and shopping intent checks
because Gemini added unrequested Ask AI steps, which would add runtime cost.
The subjective-news case failed with malformed provider JSON before graph
compilation. The other four cases passed graph and bounded intent checks.
Corrections to the intent oracle's Ask AI alias handling and the accepted icon
catalog must be distinguished from genuine authoring failures such as missing
weather behavior or malformed JSON. A new prompt discourages unrequested Ask AI.
A deployed targeted trial of a shallow legacy response schema at `b916d25`
returned syntactically valid JSON for web search, shopping, and subjective
news, but all three plans had invalid field shapes at `$.steps[0]` and failed
compiler validation (0/3). This is an intermediate schema regression, not a
successful intent retest. A following three-case trial of scoped full grammar
at `fa9d08d` returned provider generation errors in all three cases before
producing a plan. The bounded-schema seven-case run below preceded the paired
comparison above. The server still validates the full compact contract and
compiled graph.

The bounded-schema seven-case run at `865ab7b` passed web search, shopping and
events summary, each in 2.82–3.73 seconds through intent checking and excluding
persistence. Three weather or speech cases ended in provider generation errors
with HTTP 400 responses associated with the response schema before a complete
plan was available; a separate fixed-prompt probe confirmed schema dependence. The
subjective-news plan omitted required branch messages and failed compiler
validation. These are real failed attempts, not passing examples. Its Jev call
considered 40 skills and four questions and averaged 394.1 ms. The mean
2.975-second request time includes failures, while its estimated cost data are
incomplete for the three provider failures, so no complete mean cost or
first-component latency is claimed. The private report is
`/tmp/workflow-compact-bounded-final-7cases-20260930.json`.

At the earlier bounded-schema checkpoint, isolated CI for stream and CLI
coverage had passed; workflow-input and transaction coverage was still
pending. The newer accepted
contract for per-node validation, Stop, one correction retry and partial draft
recovery is not established by these runs or that interim CI evidence.

Complete-request timing includes Jev, complete Gemini generation, compiler
validation and the intent oracle. It excludes persistence, durable queue
acknowledgement, UI delivery and workflow execution. First action callback
is observed after Gemini generation begins; the table adds sequential Jev
preselection and excludes one-time catalog startup and UI transport. In the
valid-JSON retest, mean Jev preselection was 365 ms and mean Gemini generation was
2,058 ms. Cost figures use provider-reported usage, including reported
metadata and reasoning usage where available and the billed failed attempt in
that retest; they are estimates, not invoices. The earlier deployed retest
has incomplete usage on its generation failure, so its cost is not averaged in
the table. No workflow was saved, activated or executed
in these trials. Full plans and per-request diagnostics remain private in
`/tmp/workflow-compact-json-7cases-20260930.json`,
`/tmp/workflow-compact-final-7cases-20260930.json`, and
`/tmp/workflow-compact-valid-json-7cases-20260930.json`, and
`/tmp/workflow-compact-schema-targets-20260930.json`.

A separate attempt to send the entire capability union using the newer
`responseFormat` request field received HTTP 400 transport/schema-validation
responses. Those requests did not produce candidate plans and are excluded
from model-quality counts. The provider accepts the legacy
`responseJsonSchema` request field. JSON syntax alone does not establish
compiler validity or semantic correctness.

## Historical constructor experiment and architecture decision

The earlier constructor comparison below predates the selected compact-plan
route. Its Jev skill preselection was promising, but none of those three graph
constructors was ready to replace the recipe planner on that evidence alone.

The earlier approved direction on 2026-09-30 was one registry-derived Jev call to
preselect app skills and create, update, and control modes, followed by Gemini
3.8 Flash authoring a compact semantic plan with metadata, typed references,
conditions, branches, and information text. A backend compiler maps the plan
to V2 using executable contracts, without a predefined recipe restriction.
Complete authored components may stream as provisional UI previews. Full
validation and an encrypted durable queue write precede confirmation; Directus
may persist in the background. If Jev is unavailable, the regular Gemini 3.8
Flash authoring call makes the same selection and returns the same contract.
The user later requested an app-first versus direct Jev comparison and
validated node streaming with partial recovery, recorded above. The three
constructors below remain historical comparators, not production candidates.

Seven synthetic requests were evaluated with one shared Jev skill selection per
request and three downstream constructors. No workflows were saved, activated
or executed. The reported timing sums preselection and construction stages.
Jev construction includes its internal V2/readiness/composition validation;
Groq and Cerebras construction timing stops before the shared validator and
intent oracle. These asymmetric boundaries prevent an end-to-end latency
comparison. All paths exclude metadata generation, persistence, UI and skill
execution.

| Constructor after shared Jev selection | V2-valid graphs | Intent checks passed | Mean recorded stage sum, all attempts | Mean estimated USD per attempt |
| --- | ---: | ---: | ---: | ---: |
| Jev generic decision compiler | 3/7 | 2/7 | 1.408 s | $0.001157 |
| Groq GPT-OSS 120B, low reasoning | 3/7 | 2/7 | 2.709 s | $0.001829* |
| Cerebras GPT-OSS 120B, low reasoning | 4/7 | 3/7 | 1.427 s | $0.003475 |

*Groq cost averages six attempts with reported usage. One rejected generation
has unknown construction usage; it is not treated as free. Costs include the
logical path's Jev selection and are estimates, not billing receipts. Failed
attempts are included, so these averages do not describe successful delivery
latency or cost per successfully created workflow.

Jev preselection averaged **391 ms**, range **323–563 ms**, and included every
required skill in all seven requests. It also selected extra candidates, notably
web skills for dedicated domain requests. This measures required-skill recall,
not exact selection accuracy. Cold catalog loading took **1.431 s**, plus
**115 ms** registry initialization; both were performed once before the requests.

## Cases and failures

| Request | Jev | Groq | Cerebras |
| --- | --- | --- | --- |
| Today’s Berlin weather, umbrella if rain, dry message otherwise | Valid graph, wrong date range | Pass | Invalid output reference |
| Three cities’ weather, weekdays, explicit missing-forecast handling | Experimental check-count limit | Missing fallback | Missing fallback |
| Monday web search for database releases, deliver results | Pass | Pass | Pass |
| Daily refurbished ThinkPad search under EUR 700, deliver prices | Pass | Missing inline variable | Missing inline variable |
| Friday events search → Ask AI summary → chat | Free text needs generation | Rejected generated JSON | Pass |
| News → subjective AI check → separate yes/no messages | Free text needs generation | Invalid selected-input reference | Invalid selected-input reference |
| Spoken self-correction: 7 → 08:30, Berlin → Lisbon, tomorrow’s rain | Free text needs generation | Missing inline variable | Pass |

“Pass” means V2/readiness/composition validation and the bounded intent checks
passed. It does not prove runtime execution or comprehensive semantic fidelity.
The final audit corrected one false positive: weather defaults to seven days,
so a request for today's rain cannot silently omit its date window. Existing
outputs were regraded offline; no additional inference was made.

## Historical prototype implementation

- `WorkflowAuthoringPreselector`: one Jev call selects directly from the
  current workflow capability registry, plus operation, exact/AI checks and
  chat delivery. The catalog is retained for the preselector's lifetime.
- Selected context includes actual input/output schemas and public skill hints.
  There is no list of predefined workflow recipes in this experimental path.
- `WorkflowJevConstructor`: allocates node instances, then chooses fields,
  typed output bindings and edges, and compiles a V2 graph. It fails validation
  rather than saving a broken or incomplete graph.
- Shared Groq/Cerebras transport uses a single app-action variant with unique
  capability IDs, typed input schemas and canonical decoding to app/skill IDs.
- Full V2, readiness and composition validation, separate intent checks,
  token/cost/timing capture and private decision/graph diagnostics.
- Twelve focused infrastructure checks cover selection, schema preservation,
  canonical decoding, invalid graphs, usage accounting and semantic grading.

The first comparison exposed protocol mistakes: Groq rejected empty-object
requirements and overlapping union discriminators; LLM instructions omitted
some grammar and conflicted about message variables. Those were repaired before
the final comparison. These initial failures are not model-quality scores.

## Interpretation and remaining work

Keep the preselection finding, but do not rank Cerebras, Groq, and the Jev
compiler by end-to-end speed from this table. Cerebras passed one more case in
this small sample; seven examples are insufficient to select a production
constructor. No provider load or rate-limit test was performed. The subsequent
approved architecture uses Gemini 3.8 Flash for compact semantic planning.

The compact semantic plan and generic V2 compiler now exist in the task
workspace. Integrated verification must establish typed references,
type-specific branching, dates, omitted defaults, failure handling, and
atomic persistence through the actual workspace and chat routes. Under the
newer accepted contract, an invalid node never reaches the client or save;
after one failed correction, only the already validated prefix may be saved
disabled as a visible partial result.

Jev-only graph planning needs dependency-aware topology decisions and a way to
obtain required free text. Its current limits are 16 nodes, three instances of a
skill, two checks of each kind, one array item and two message sources. These
are prototype limits, not intrinsic Jev limits. Jev cannot generate arbitrary
new text; copying request spans or deterministic templates is sufficient only
for a subset of fields. The existing required LLM metadata generation could
also produce necessary text fields, but that combination was not tested here.

Before accepting the generic path: verify edits and mixed/multiple workflows,
atomic saving and guarded undo, regular Gemini 3.8 Flash selection on Jev
outage, and the generic path through CLI and web. The exact-source comparison
has inference-through-validation timing, but lacks encrypted durable-queue
acknowledgement timing and full integrated CI evidence.

The broader capability metadata audit still has existing calendar classification
and weather-example findings. This focused experiment does not clear that audit
or prove every registered skill supports reliable natural-language authoring.

## Evidence and reproducibility

Final live inference used exact session source in an isolated API subprocess
with the deployed capability registry, against base revision
`bd84c3890af35c88953ada0ea959e6e79ee91594`. Shared service source was not changed
by the subprocess. Synthetic raw reports remain private under `/tmp`:
`workflow-authoring-final-20260930.json` (and its offline regraded copy).

Source SHA-256 values during final generation:

- Preselection: `196bd255ccb61ec9f4e0d4a2ef2e6f187895af3c74066d67c8d98d2f69a5cf78`
- Jev constructor: `2fe9937fa66a89ca89a62087d2d75302082c72789dfcda876c288da37b7f9c5d`
- Harness before offline oracle correction: `9d059c317a99d99e0538c8c071a5c7ada427b1fc9119aba1c2837c92601fe7c8`

Reproduction inside an API container containing the final source:

```sh
python -m backend.scripts.benchmark_workflow_authoring --output /tmp/workflow-authoring.json
```

This explicitly incurs inference charges and never persists a workflow.

Price estimates use Jev $0.042/M input tokens, Groq $0.15/M input,
$0.075/M cached input and $0.60/M output, and Cerebras $0.35/M input and
$0.75/M output. Public sources checked on 2026-09-30:
[Jev](https://openrouter.ai/typesafe/jev-1.13),
[Groq](https://console.groq.com/docs/model/openai/gpt-oss-120b),
[Cerebras model data](https://api.cerebras.ai/public/v1/models/gpt-oss-120b).

Provider contracts:
[Jev decisions](https://docs.typesafe.ai/api),
[Groq structured output](https://console.groq.com/docs/structured-outputs),
[Cerebras structured output](https://inference-docs.cerebras.ai/capabilities/structured-outputs).
