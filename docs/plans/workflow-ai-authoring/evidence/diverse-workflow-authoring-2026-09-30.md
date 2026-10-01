# Diverse workflow authoring: exact requests and results

Synthetic authoring checks on dev. All created workflows were disabled, never run, and deleted after inspection. These checks establish generated structure and intent; they do not execute the requested app skills.

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
- Transcript correction remains enabled; the successful raw spoken request does not establish a controlled quality comparison.
- Mixed create/edit Stop recovery and live clarification chat still need their accepted integrated evidence.

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
