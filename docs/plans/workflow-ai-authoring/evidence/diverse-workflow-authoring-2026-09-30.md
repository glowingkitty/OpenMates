# Diverse workflow authoring: exact requests and results

Synthetic authoring checks on dev. All created workflows were disabled, never run, and deleted after inspection. These checks establish generated structure and intent; they do not execute the requested app skills.

The current product revision is `15b507d`. The latest tested result for each of the six scenario families matched its instruction after the recorded fixes. These runs span different revisions; they are not a repeated reliability benchmark on one release. Three additional raw/clear transcript cases passed. Five final browser/REST/CLI cases passed, and one live clarification turn resolved the original workflow without executing its future actions. Exact requests, summaries, costs and limitations follow below.

Initial six cases used revision `557ebc1b`. Two targeted reruns used `607cd834`. Four initial cases passed; the weather rerun passed after the Jev branching fix, while shopping remained partial because its euro marketplace was omitted. Later corrections and billing proof are recorded below when verified.

CLI wall time includes the HTTP round trip and persistence. Planner/service times are reported separately. First component is measured **inside Gemini generation**, excluding Jev and client rendering. USD values are provider-cost estimates, not user credit charges; one aborted retry has incomplete cost metering.

## 1. PASS

**Exact initial input**

> Every week, search the web for practical research about AI agents and send me the search results in chat. Name it Research Search QA q7n4.

**Generated workflow**: Monday 09:00 UTC (defaults) → web.search → Send chat with typed search results.

Initial CLI: 4.636s; planner: 2.427s; service: 4.043s; estimated cost: $0.00367059; complete cost metering: true.

## 2. FAIL

**Exact initial input**

> Every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than 150 euros and send me the matching products in chat. Name it Headphone Search QA q7n4.

**Generated workflow**: Disabled partial: Friday 09:00 (wrong requested18:00) → shopping.search_products(category electronics,max_price150) → typed results Send. Jev incorrectly required exact Check; both internal attempts failed check_mode_omitted. Marketplace/currency was omitted.

Initial CLI: 5.148s; planner: 3.336s; service: 4.288s; estimated cost: $0.00821935; complete cost metering: true.

**Targeted rerun: PARTIAL**

> Every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than 150 euros and send me the matching products in chat. Name it Headphone Search QA r8v2.

Friday 18:00 UTC → shopping.search_products (headphones, electronics, max_price:150) → typed results chat message. Jev correctly chose no check. Country/currency omitted, so the euro constraint was not guaranteed.

CLI: 3.605s; planner: 2.063s; Jev: 0.381s; service: 3.001s; Gemini attempts: 1; estimated cost: $0.00473029; complete cost metering: true.

## 3. PASS

**Exact initial input**

> Every Monday at 08:00 UTC, find high-protein vegetarian breakfast recipes without peanuts and send me the recipes in chat. Name it Breakfast Recipe QA q7n4.

**Generated workflow**: Monday08:00UTC → nutrition.search_recipes (high protein, vegetarian, peanut-free, Breakfast, excluded peanuts) → typed recipe results Send.

Initial CLI: 3.657s; planner: 2.195s; service: 3.109s; estimated cost: $0.00444788; complete cost metering: true.

## 4. PASS

**Exact initial input**

> Every weekday at 09:00 London time, search for news about AI regulation. If the news is important for a small European startup, send me the relevant news in chat; otherwise send a message saying there are no important updates. Name it wf3e12-news-20260930.

**Generated workflow**: Weekdays09:00Europe/London → news.search(AI regulation,relevance tosmall Europeanstartups) → subjective AI Check over realresults → yes:Send relevantnews;no:Send no-important-updates. No unrequested AskAI.

Initial CLI: 4.296s; planner: 2.742s; service: 3.693s; estimated cost: $0.00490152; complete cost metering: true.

## 5. PARTIAL

**Exact initial input**

> Every day at 07:00 Berlin time, get today’s weather for Berlin and Lisbon. Compare both forecasts with AI, recommend which city is better for an outdoor walk, and send me one combined answer in chat. Name it wf3e12-weather-20260930.

**Generated workflow**: Daily07:00Europe/Berlin → Berlin and Lisbon weather.forecast with runtime today dates → AskAI using BOTH actual forecastresults → Send one combinedanswer. Saved correctdisabledgraph but falsely required Check; both attempts failed check_mode_omitted.

Initial CLI: 5.521s; planner: 4.033s; service: 4.964s; estimated cost: $0.00864874; complete cost metering: true.

**Targeted rerun: PASS (one retry)**

> Every day at 07:00 Berlin time, get today’s weather for Berlin and Lisbon. Compare both forecasts with AI, recommend which city is better for an outdoor walk, and send me one combined answer in chat. Name it wf3e12-weather-retest-20260930.

Daily 07:00 Europe/Berlin → Berlin and Lisbon weather.forecast with today date objects → Ask AI comparing BOTH actual forecast results → one combined chat message. No check. The first attempt emitted invalid inner JSON; the correction succeeded.

CLI: 7.352s; planner: 4.417s; Jev: 0.414s; service: 6.605s; Gemini attempts: 2; estimated cost: $0.00913402; complete cost metering: false.

## 6. PASS

**Exact initial input**

> Um, make this every Tuesday at eight in Madrid—sorry, no, Thursday at nine in Lisbon. Find local AI meetups—actually robotics meetups—and, uh, send me a chat summary of the results. Name it wf3e12-events-20260930.

**Generated workflow**: Thursday09:00Europe/Lisbon → events.search(Lisbon robotics,physical,count10) → AskAI summaryusingactualeventresults → Send summary. Resolved all spoken corrections.

Initial CLI: 3.867s; planner: 2.384s; service: 3.311s; estimated cost: $0.00659824; complete cost metering: true.

## Web verification

[Isolated CI run 36789254173](https://github.com/glowingkitty/OpenMates/actions/runs/36789254173) passed the single focused stream testcase at source `a94a685b`, equivalent to deployed product revision `607cd834`. It checks immediate empty fullscreen before the HTTP response, processing above nodes, header metadata, individual validated nodes, inert controls, the fixed shared composer, no placeholder GET/save, disconnect recovery, multi-workflow workspace view, and Stop/partial recovery.

A single live dev creation was prepared, but authentication failed before any authoring request. Numbered test accounts 9, 10 and 1 rejected two-factor codes; UTC clocks and canonical/worktree credential hashes matched. No AI call, created workflow, real browser generation timing or cost exists for that attempt. Product authentication was not changed.

## Corrections after these runs

- Revision `607cd834` distinguishes search filters and AI comparisons from requested yes/no branching; generated daily/weekly clock times must be explicit.
- Shopping metadata now explains marketplace currency and EUR defaults; bounded Amazon searches now omit products without a usable price. The final targeted CLI proof passed on revision `127f161f`.
- The billing audit found authoring estimates did not charge the ledger or create Billing history entries. A focused billing integration now meters each Jev/Gemini call with catalog rates and stable ledger identities, preserves token fields in Billing history, and fails the session if settlement fails. Thirty-one focused checks passed, the scoped deployment is `127f161f`, and the single real CLI debit/history/replay proof passed. No historical charges are being added.

Recorded provider-cost estimates for the eight initial/rerun requests total $0.05035063; metering is incomplete for the weather retry, so this is not an exact provider invoice or credit debit.

## Remaining verification

- Wider capability/currency combinations and JSON-retry reliability remain outside this small sample.
- The bounded raw-versus-clean CLI comparison below supports bypassing separate workflow transcript correction. Actual speech-recognition errors and wider language coverage remain unmeasured.
- Same-ID stopped-edit recovery and Undo passed controlled-generation browser coverage with real persistence. The live clarification turn passed exact target lookup, focus activation and one necessary question. A live interrupted model edit and completing an edit after the clarification reply remain unmeasured.

## Final targeted proof scope

The opt-in `scripts/workflow_authoring_billing_real_test.py` sends one headphone request, checks Friday 18:00 UTC, the EUR marketplace `de`, max_price 150 and typed result delivery, reconciles the wallet debit with independent catalog calculations and Billing history, then replays the same idempotency key without more inference or charges. It deletes only the disabled workflow it created. CLI wall time excludes lock waiting.

## Final targeted result: PASS (2026-10-01)

**Exact input**

> Every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than 150 euros and send me the matching products in chat. Name it Headphone Billing QA 0950505f.

**Generated workflow**: Disabled Friday 18:00 UTC → shopping.search_products(query:noise-cancelling headphones, category:electronics, country:de, max_price:150) → Send chat with typed `$nodes.search_headphones.output.results`. No Check or extra Ask AI. The shopping action was not executed; mocked provider coverage separately verifies unpriced products cannot pass a price bound.

Revision `127f161f55821ce98c7b7808aec1d487b8e59f0b`, healthy runtime `docker-13515302`. CLI wall: **6.114s**; server service: **5.541s**; planner including billing/validation: **3.226s**; Jev selection including credit precheck/settlement: **1.035s**; Gemini generation: **1.656s**. First validated header: **1.2934s inside Gemini**, excluding Jev, session setup, billing and client rendering. Stage timings can overlap; they are not a disjoint sum.

Exactly one Jev and one Gemini call; no retry. Complete estimated provider cost: **$0.00486457**. Actual debit: **13 credits**, independently reconciled using catalog rates and the existing floor/minimum-credit rule:

| Model | Input tokens | Output tokens | Credits |
| --- | ---: | ---: | ---: |
| typesafe/jev-1.13 | 13,823 | 950 (free) | 1 |
| google/gemini-3.8-flash | 4,802 | 182 | 12 |

The same two entries were visible through `settings billing usage`, with app `workflows`, skill `create-or-modify`, model, tokens and credits. Replaying the same UUID idempotency key took **0.826s**, returned the same session/workflow, and left both wallet and usage-entry IDs unchanged: no additional inference or charge. The disabled workflow was deleted afterward. Private receipt: `/tmp/workflow-billing-final3e12.json` (0600).

The initial proof harness used a named idempotency key and was rejected with HTTP422 before planning or billing. Changing that harness value to a UUID enabled the successful proof; the rejected preflight created no workflow or charge.

[Billing settings CI run 36796094385](https://github.com/glowingkitty/OpenMates/actions/runs/36796094385) passed one case with no skips or failures at source `98433d1810`, harness `c3127d67`. It checks authoring labels, two billed provider requests, credits, day-total reconciliation and the Apps summary. A prior attempt failed only because the fixture added a highest-credit app while assertions assumed fixed row positions; the corrected test selects rows by app name.

Vercel deployment succeeded for the same product revision. Deployment gates passed lint, translations, SDK privacy/boundary audits and ten affected backend test files. No unrelated browser suite was run.

## Raw transcript versus clear instruction (2026-10-01)

Three capped real-inference requests on product revision `127f161f` passed final intent checks. This compares supplied transcript text, not speech-recognition accuracy. All generated workflows remained disabled, were never executed, and were deleted with absence verified. Private receipt: `/tmp/workflow-raw-voice-quality3e12.json` (0600).

### Raw weather with self-corrections: PASS

> Um, make a workflow every day at seven Berlin time, actually no, every weekday at eight thirty Berlin time. Check today's weather in Paris, sorry, tomorrow's weather in Berlin. If rain is expected, send me 'Take an umbrella in Berlin tomorrow' in chat; if it isn't, send me 'No rain expected in Berlin tomorrow' in chat. Name it Weather Raw Voice QA ba678e7e.

**Output**: Weekdays 08:30 Europe/Berlin → Berlin tomorrow forecast → exact rain_expected Check → yes: “Take an umbrella in Berlin tomorrow”; no: “No rain expected in Berlin tomorrow”. No Ask AI.

CLI wall: **6.204s**; planner: **3.984s**; service: **5.614s**; estimated provider cost: **$0.00537710**; actual authoring charge: **15 credits**. Cost and billing usage were complete.

### Matching clear weather instruction: PASS

> Every weekday at 08:30 Berlin time, check tomorrow's weather in Berlin. If rain is expected, send me 'Take an umbrella in Berlin tomorrow' in chat; otherwise send me 'No rain expected in Berlin tomorrow' in chat. Name it Weather Clean Voice QA ba678e7e.

**Output**: Weekdays 08:30 Europe/Berlin → Berlin tomorrow forecast → exact rain_expected Check → yes: “Take an umbrella in Berlin tomorrow”; no: “No rain expected in Berlin tomorrow”. No Ask AI.

CLI wall: **5.409s**; planner: **3.749s**; service: **4.851s**; estimated provider cost: **$0.00531517**; actual authoring charge: **15 credits**. Cost and billing usage were complete.

### Raw shopping with self-corrections: PASS

> Um, every Thursday at six p.m. Berlin time, find noise-cancelling headphones for under 120 dollars and send the matching products in chat. Wait, no: every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than 150 euros, and send me the matching products in chat. Name it Headphone Raw Voice QA ba678e7e.

**Output**: Friday 18:00 UTC → shopping.search_products (noise-cancelling headphones, country de, max_price 150 EUR) → Send chat with typed matching-product results. No Check or Ask AI.

CLI wall: **7.428s**; planner: **5.791s**; service: **6.847s**; estimated provider cost: **$0.00490913**; actual authoring charge: **13 credits**. Cost and billing usage were complete.

The weather pair preserves the same corrected day, clock, timezone, city, runtime date and branch text. The raw shopping result matches the earlier clean headphone baseline. Together with the earlier raw Lisbon robotics case, this supports removing the separate workflow transcript-correction call by default. The direct authoring costs above do not include a transcription/correction call and do not measure the amount of audio latency saved. The operational correction path remains available for rollback; ordinary chat keeps its current correction flow.
## Selected-workflow clarification follow-through (2026-10-01)

One live clarification baseline on revision `127f161f` activated
`workflows.clarify_workflows` and called only `workflows.search`, without running
events, calendar, maps or delivery actions. It did not resolve the selected
workflow: exact-title, prefix and empty queries each returned zero results.
The search skill defaulted to an empty in-memory repository while authoring used
Directus. The deployed fix on `15b507d` selects persisted storage, supports an exact
owner-checked workflow ID, supplies the selected graph with credential fields
removed, and asks one necessary question at a time. Five focused search tests
pass; the post-deployment verification is recorded below.

The baseline took 25.884 seconds and charged 91 credits for an ordinary focused
chat turn. These are not workflow-authoring stage costs. The disabled original
was unchanged, no copy was created, and both disposable objects were deleted.


## Final integration and clarification proof — 2026-10-01

Deployed to dev and Vercel as `15b507d395a03ba74ba70aa42d1140cdd63b2435`.
API and 12 dependent workers were updated under coordinated restart
`docker-dbc72436`; all were running and healthy. Deployment gates passed lint,
registry/locale validation and six affected pytest files.

- [Workflow input/voice CI](https://github.com/glowingkitty/OpenMates/actions/runs/36805982863): two cases passed at source `0c9ecc0e`; raw submission, failure recovery, editor target, exact focus auto-send, consume-once navigation and existing create/edit/dirty-state flows.
- [Stream/partial-edit CI](https://github.com/glowingkitty/OpenMates/actions/runs/36804241207): two cases passed at source `a1da94c9`; immediate fullscreen, validated updates, stopped same-ID disabled edit, retained nodes/edges, highlight, full Undo and later-version conflict.
- [REST/CLI conditional-save/search CI](https://github.com/glowingkitty/OpenMates/actions/runs/36804247471): one case passed at source `a1da94c9`; manual literal branch edits, persisted exact-ID graph lookup and future-schedule enable/disable.

All five passed without skips or flakes. Generation/session responses in browser
cases are controlled; workflow persistence is real. They do not prove a live
browser Gemini interruption. The deployed patch was integrated with unrelated
upstream website-state cleanup and translations without changing these fixes.

### One live clarification turn

Exact synthetic input (the IDs below belonged only to deleted test objects):

> @focus:workflows:clarify_workflows Also add searches for AI meetups and queer meetups.
>
> Workflow editor context: I was changing my existing workflow "Clarify Voice Edit QA 0ab67097" (ID e3776e43-cca9-4654-aaf5-930945350cd0). Keep this workflow as the target. Clarify the change before carrying out any of the workflow's future search or delivery actions.

The assistant resolved the exact original through one `workflows.search` result,
activated the focus mode, and asked: “To update the workflow with the additional
searches for AI meetups and queer meetups, what location (such as a specific city,
region, or online/virtual) should be used?” No events/calendar/maps skill or edit
ran. The original graph remained unchanged; no copy appeared. The chat and
workflow were deleted and absence verified.

CLI chat wall time: **21.688 seconds**; actual wallet debit: **45 credits**.
This is a regular focused chat turn, not a workflow-authoring duration or price.
The first baseline failed lookup, took 25.884 seconds and charged 91 credits;
these single samples do not establish a causal latency/cost reduction.

Private receipt: `/tmp/workflow-clarification-postdeploy3e12.json` (0600).
Its original harness exit was 1 because the check used `focus-mode-activation`
while the decrypted CLI embed uses `focus_mode_activation`. The embed confirms
`focus_id=workflows-clarify_workflows`. The harness spelling check was fixed;
re-evaluating the existing receipt passed all eight checks without another AI
call (`/tmp/workflow-clarification-postdeploy-recheck3e12.json`).

Remaining measurement limits: actual ASR recognition and languages beyond the
small supplied-text corpus; live browser AI timing (test-account authentication
blocked); a live interrupted Gemini edit; and completing the edit after the
clarification reply. Registered skill coverage is broader than the live samples.
