# Registry-driven workflow authoring comparison — 2026-09-30

## Result

Jev skill preselection is promising. None of the graph constructors tested here
is ready to replace the production planner. This is an engineering prototype;
the existing CLI/web input route still uses the earlier planner.

Seven synthetic requests were evaluated with one shared Jev skill selection per
request and three downstream constructors. No workflows were saved, activated
or executed. Timing includes selection and graph construction; it excludes
workflow title/description/icon generation, persistence, UI and skill execution.

| Constructor after shared Jev selection | V2-valid graphs | Intent checks passed | Mean planning time, all attempts | Mean estimated USD per attempt |
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

## Implemented

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

## Recommendation and remaining work

Keep Jev preselection. Use Cerebras GPT-OSS 120B as the leading next constructor
candidate because of its observed speed and broader successful examples, while
retaining full validation. Seven examples are insufficient to choose a
production default. Groq was slower in this sample; no provider load or rate-limit
test was performed.

The next improvement should be a small authoring representation compiled into
V2, with canonical output-reference choices and type-specific branching. This
would reduce the ways either model can emit syntactically valid but unusable
references. Add semantic checks for dates, omitted defaults and requested
failure handling. A bounded repair must use validator errors, preserve intent,
and never save an invalid result.

Jev-only graph planning needs dependency-aware topology decisions and a way to
obtain required free text. Its current limits are 16 nodes, three instances of a
skill, two checks of each kind, one array item and two message sources. These
are prototype limits, not intrinsic Jev limits. Jev cannot generate arbitrary
new text; copying request spans or deterministic templates is sufficient only
for a subset of fields. The existing required LLM metadata generation could
also produce necessary text fields, but that combination was not tested here.

Before replacing the production planner: cover edits and mixed/multiple
workflows, preserve atomic saving and guarded undo, add the existing Gemini
fallback behavior, and verify the generic path through CLI and web. Measure
metadata generation and Dragonfly acknowledgement alongside planning before
claiming an end-to-end response under two seconds.

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
