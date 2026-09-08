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

Coordinator must assign shared appointment relevance / decoded-field investigation.
Retry the exact opening after correction. Source has not been shared or converted;
no catalog, translations, memories, or narration changed. Phone/laptop maps,
links, fullscreens, follow-ups and composer review remain pending because content
failed. Speech remains held for user-confirmed pilot. No admission claimed.

Browser automation must respect the current GitHub isolation cutover and any
dispatcher migration hold; do not use older deployed-Playwright bypasses.

API returned HTTP 502 twice during result inspection after a shared API restart.
`sessions.py wait-health --session 235f --timeout 45 --poll 10` reported ready;
subsequent result reads succeeded. No runtime mutation was performed here.
