# TASK-584: Berlin doctor appointment handoff

- Worker: session `235f`, Codex thread `01a080f4-f82a-7270-b846-668e3ce8c437`.
- Worktree: `agent-235f`, initial base `d01d7d4e9`; distinct from coordinator `4aa6`.
- Source created 2026-09-08 through current source CLI against dev.
- Source chat: `64ac5778-548b-4ef2-9d0c-f1af288f049f`.
- Assistant turn: `e6ff634e-a569-57b7-a554-f0217014023e`.
- Opening, unchanged: “I fell while playing basketball today and my hand still hurts a lot. Find me a doctor appointment in Berlin for as soon as possible.”
- Routing: Melvin / medical_health / Gemini 3.5 Flash-Lite; English.

## Rejected candidate: stop before continuation or publication

The assistant recommends Sebastian Kopf as the earliest suitable appointment,
September 9 at 08:00 Berlin time. Actual child result
`fbbf6de1-0b16-459b-934c-4e0c5aa04f2a` has both `visit_motive` and
`service_name` equal to `Eigenbluttherapie (PRP) Gelenkbehandlung`.
This is a specific treatment appointment, not an initial assessment of the
reported injury. The assistant omits this restriction and offers a follow-up
suggestion to book that appointment. Do not rewrite or regenerate to hide it.

Secondary observed data issue: parent `2b384969-11b6-4c6e-b76d-1762cc20de43`
decodes `city` as Berlin followed by the entire preview_results list. Child
`speciality` includes a literal `languages[0]:` suffix. These are decoded CLI
observations; browser impact has not been established.

Read-only lead for shared fix owner:
`backend/apps/health/skills/search_appointments_skill.py`,
`_select_jameda_services_for_request` falls back from general motives to all
non-noise motives. Check actual deployed runtime before attributing cause.
No shared product code was changed by this worker.

## Evidence and next action

Use the assigned current CLI entry point with `--api-url https://api.dev.openmates.org`:

```text
chats show 64ac5778-548b-4ef2-9d0c-f1af288f049f --all --raw --json
embeds show 2b384969-11b6-4c6e-b76d-1762cc20de43 --json
embeds show fbbf6de1-0b16-459b-934c-4e0c5aa04f2a --json
embeds show 14f3f60e-3762-4d9d-8aec-639d8fdac296 --json
```

Coordinator assigned appointment-selection investigation to this worker on
2026-09-08. Retry the exact opening only after correction. Source has not been shared or converted;
no catalog, translations, memories, or narration changed. Phone/laptop maps,
links, fullscreens, follow-ups and composer review remain pending because content
failed. Speech remains held for user-confirmed pilot. No admission claimed.

Browser automation must respect the current GitHub isolation cutover and any
dispatcher migration hold; do not use older deployed-Playwright bypasses.

API returned HTTP 502 twice during result inspection after a shared API restart.
`sessions.py wait-health --session 235f --timeout 45 --poll 10` reported ready;
subsequent result reads succeeded. No runtime mutation was performed here.

## Investigation update: 2026-09-08

The saved chat was reread through the real CLI. Its server assistant message ID is
`3349741f-09b0-4f97-9ab3-b52aecd7c687`; the earlier recorded turn ID is its
`clientMessageId`. The original prompt is unchanged.

Selection trace in the current source:

1. `AppointmentSearchRequest.visit_motive_category` defaults to `None`.
2. Jameda `_select_jameda_services_for_request` first tries general motives when
   no category/procedure was supplied. If none match, it returns all non-noise
   motives. The observed PRP service is not excluded by that fallback.
3. The selected calendar service ID is used when fetching its specific slots.
   Result `service_name` and `visit_motive` preserve the PRP label; the observed
   result has service ID `620472`, practice `236873`, and a corresponding booking URL.
4. Provider results are sorted by slot time, grouped by practice and service ID,
   and then capped within insurance buckets. There is no later purpose check.
5. The assistant calls the result an option for hand trauma without disclosing
   that its bookable service is PRP treatment. The response schema does not hide
   `service_name` or `visit_motive` from inference.

A local diagnostic with the observed service ID/name selects `[620472]` with
category `None` and `[]` with category `general`. This isolates a viable code
path; it is not a replay of the complete historical provider response and does
not establish every argument sent in the original tool request.

`python3 -m pytest backend/tests/test_health_search_appointments_skill.py -q`
passed all 12 unchanged tests. `specifications.py check-test` reports missing
contract metadata for all 12; repository Specification discovery found no
appointment-selection contract. App Skill Execution explicitly excludes
provider-specific request/result fields. Existing passing tests therefore do
not authorize the proposed default-purpose change.

Superseded, unapproved initial review bundle: `specifications/features/health-appointment-search/`.
It defines consultation-default selection, explicit-purpose preservation,
provider eligibility, service-bound availability and faithful descriptions.
It excludes diagnosis, emergency-triage policy and speciality-from-symptoms
selection. No product code or test assertions changed before approval.

After approval: map/extend existing health tests with the observed PRP fallback
case and positive consultation/procedure controls; record red, implement the
small provider filter and schema-hint change, and verify green. Before any live
runtime change obtain the coordinator lease and explicit target. Real API,
CLI, SDK and browser verification must honor current isolation migration holds.
Sonnet's task has been notified that no shared inference files were touched.


## Full APP-SKILL revision requested by user

The prior narrow feature draft was not approved and is superseded, including its
`1e82dd0439baac29…` PDF. It must not be approved or used for implementation.
The current bundle is
`specifications/features/app-skills/health-search-appointments/`, with identity
`feature.app-skill.health-search-appointments@1` and title
“Health Appointment Search — App Skill”. It follows the registered
`health/search_appointments` name and travel-search's app-skill hierarchy.

Discovery covered the active worktree and canonical Specification catalog,
`feature.app-skill.travel-search`, inherited App Skill Execution and Platform
Parity, Health `app.yml`, provider filtering/result code and health embed
surfaces. No pre-existing health-search app-skill contract was found. The Health
README contains old planning descriptions, so it was not treated as live capability
truth. No duplicate focus-mode Specification was created.

The full draft has 13 requirements, each linked to exactly two concrete synthetic
examples (26 total): input validation/batching, provider selection, initial visit
purpose, explicit categories/procedures, city/speciality, insurance/patient
eligibility, telehealth/language, search window/order, grouping, booking provenance,
maps/enrichment, distinct failure outcomes and cross-client parity.

Observable guarantees are in scope. Prompt wording, tactical agent instructions,
focus behavior, diagnosis, triage policy and symptom-to-speciality selection are
explicitly excluded. The original synthetic injury example retains the invariant
that a PRP treatment appointment cannot substitute for initial consultation.
The coordinator retains the separate agent-instructions decision.

Review evidence: the existing implementation admits PRP through the omitted-category
fallback, lacks language/telehealth evidence for Jameda, and can clear one provider's
failure when the other returns results. These are review findings, not claims that
all new guarantees currently pass. Schema validation lists city as required while
the skill's own required-field partition only checks speciality. The broader draft
makes these observable guarantees explicit; it does not silently authorize fixes.

Validation passed for the revised bundle; existing 12 unchanged filter tests passed
in the prior investigation. No product code or tests have been changed, no candidate
has been regenerated, no runtime has been mutated, and no approval is inferred.


Current exact review fingerprint:
`29b18dd32ac9fb1019f93a32584c9f7427bf988c8db2fea338374096e8fb440a`.
PDF and approval artifact:
`/tmp/opencode/specification-approvals/feature.app-skill.health-search-appointments-29b18dd32ac9fb10.pdf`
and the same basename with `.approval.json`. The canonical session wrapper
uploaded the PDF. Full Specification/examples and inline additions were checked;
its rendered cover was visually inspected. Generated artifact freshness and
all 13 requirement-to-example counts passed.

User approved the design boundary (observable guarantees versus exact prompt
wording/tactics) during this revision. That boundary was already reflected in
the full draft. It does not approve the exact Specification fingerprint above.
No duplicate decision question about that boundary is needed.

## Current implementation handoff (supersedes draft status above)

User explicitly approved full fingerprint
`29b18dd32ac9fb1019f93a32584c9f7427bf988c8db2fea338374096e8fb440a`;
approval recorded for session 235f from the original `.approval.json` artifact.
All 26 examples and 13 requirement mappings remain unchanged. PDF worker TASK-6152
reports corrected adjacent examples delivered in commit `f5b6b5acf786a4801aa6f81952260ac81c43a0d9`.

Health implementation now rejects the PRP fallback for initial consultation,
validates requests, checks provider eligibility evidence, orders timezone-aware
slots within the window, preserves provider/service grouping, and exposes partial
provider failures. Follow-up searches preserve existing-patient eligibility.
39 focused supporting tests pass; scoped Python lint, contract-test metadata,
and SDK/CLI parity audit pass. Tests cover working diff based on
`7bf8f5aa3b5ff48436cab02167b98648db1eb66e`, not a live runtime deployment.
Full real API/CLI/SDK and browser proof are still pending. No candidate regeneration.

No external job is running. Prior test process 33435 was reconciled; latest 39-test
process 58653 completed. Parity/metadata/lease command 61316 completed successfully.
Runtime target/lease request remains coordinator activity
`aad38b09766ba54ccee0a0f1e1b32de90b4614238bc840a5d3d93bf6807fcb0b`.
No runtime mutation is authorized yet. Next source command:
`python3 scripts/sessions.py prepare-deploy --session 235f`. After a scoped commit,
coordinator must grant the exact source target and service lease before reload.
No audio generation; no changes to shared inference files.
