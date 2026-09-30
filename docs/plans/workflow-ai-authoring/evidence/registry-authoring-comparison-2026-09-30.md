# Registry-driven workflow authoring comparison — 2026-09-30

## Current compact-plan trial and implementation state

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

| Jev route | V2-valid | Bounded intent checks | Required-skill recall | Extra skill selections | Median Jev selection | Median complete request | Median first preview after Gemini starts | Estimated total cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct skill selection | 6/7 | 4/7 | 100% | 10 | 351 ms | 2.375 s | 1.726 s | $0.031747, incomplete |
| App first, parallel per-app skills | 7/7 | 6/7 | 100% | 10 | 650 ms | 2.546 s | 1.505 s | $0.032562, complete estimate |

Direct selection missed the weekly weather schedule time because the authored
plan used an incorrect `at` value; the time handling fix is pending retest.
Both modes added an unrequested Ask AI step in the subjective AI-check case,
which would add runtime cost. Direct selection's events case had a provider
generation failure after one complete preview component, so its graph and
intent scores failed and its provider usage estimate is incomplete. Staged
selection passed those events checks in its one attempt. These differing
outcomes mix model sampling and route effects; the table alone cannot assign
the cause.

The first-preview clock starts when Gemini generation starts and stops at the
first complete callback, which may be a workflow header or trigger rather than
the first executable action. It excludes Jev selection and client transport;
the table does not measure time to a validated first action. Complete-request
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

Isolated CI at this checkpoint: CLI `3552920d`, transaction `248a1316`, and
stream `65cc2a70` passed. Workflow input `26af5fe6` failed a mobile layout
case. Focused checks passed 13 planner, 10 app-skill embed, 2 chat, 32
workflow-input helper, and 38 provider/compiler tests. A flex-layout fix and
a new coordinated CI run beginning `7d` are pending verification. These are
scoped interim results, not a complete CLI or product rollout verdict.

### Earlier compact-plan trials

Before the paired comparison above, the same seven synthetic requests had four
live compact-plan runs.
Each result is a separate attempt, not an offline regrading of another run.
Provider prompts, schema handling, and bounded intent checks changed between
revisions, so a difference between rows is not a measured model improvement.

| Live run and source | V2-valid | Intent checks | Mean complete request | Mean first complete component, including Jev | Mean estimated USD per attempt |
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
acknowledgement, UI delivery and workflow execution. First complete component
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
