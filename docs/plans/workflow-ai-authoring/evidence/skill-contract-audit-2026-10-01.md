# Workflow skill safety and deterministic contract audit

Date: 2026-10-01. Task: TASK-3854. No AI inference, paid providers, or background
generation jobs were invoked by this audit.

## Scope and findings

The initial dev CLI inventory advertised 38 enabled app skills. All 38 example
inputs and declared output references compiled, but that alone did not establish
correct execution, usable returned values, approval, or billing ownership.

| Finding | Repair |
| --- | --- |
| Queued media jobs were treated as completed steps; worker billing and workflow billing had separate settlement paths | Exclude `async_job` and `sandbox` until completed-job continuation and one billing owner exist; reject legacy dispatch before billing/provider work |
| `openmates.share-usecase` requires approval and forbids unattended execution, with no per-run approval path | Exclude `approval: always` and `unattended: false` contracts and reject dispatch |
| Social-media search/get-posts enqueue jobs despite declaring synchronous execution | Correct both classifications to `async_job`, so the same guard applies |
| Skill dispatch accepted authored owner/private execution context and did not consistently supply the trusted workflow owner | Strip authored private context and inject the authenticated owner and external-request flag |
| Code/OpenMates documentation and flight lookup returned useful content outside `results` | Project documentation and flight data into declared results, preserving raw data and truthful counts |
| Rain-radar summary was an object and its timeline was absent from declared results | Return a string summary and expose timeline frames as results |
| Calculation omitted an integer result count | Return one result for a successful calculation, zero without a result |
| Multi-URL web reads exposed empty top-level text | Join page text with source URL headers, retaining separate results and aggregate status |

These guards temporarily exclude 10 of the original 38: audio.generate,
audio.speak, images.generate, images.generate_draft, music.generate,
videos.generate, videos.create, social_media.search, social_media.get-posts,
and openmates.share-usecase. They do not disable these skills in ordinary chat.
Source also includes the previously absent `openmates.get-docs` and queued
`models3d.generate`; the latter is excluded. The source audit therefore checks
29 enabled skills. Readiness rejects activation/runs of saved unsafe graphs;
disabled drafts remain inspectable. The adapter adds an independent dispatch
guard so saved or directly dispatched unsafe nodes cannot bypass discovery.

## Repeatable checks

With the backend Python environment and repository root on `PYTHONPATH`:

```sh
python backend/scripts/audit_workflow_authoring_contracts.py
python scripts/audit_workflow_capabilities.py
python -m pytest -q backend/tests/test_workflow_authoring_contract_audit.py backend/tests/test_workflow_capability_metadata.py backend/tests/test_workflow_app_skill_adapter.py backend/tests/test_workflow_skill_output_contracts.py
```

| Check | Result |
| --- | --- |
| All enabled source skills: schema-valid examples through actual flat-node authoring and graph compiler | 29 pass |
| Every declared top-level output: typed downstream reference in a complete graph | 135 pass |
| Invalid input rejected without mutating the accepted prefix | 29 pass |
| Unknown output reference rejected | 29 pass |
| Metadata classification audit | Pass |
| Focused registry, dispatch/billing, output-value and audit regressions | 59 pass |
| Ruff on changed Python files | Pass |

`cli-workflow-skill-safety.spec.ts` adds one isolated CLI integration case:
all ten previously advertised exclusions are disabled, and source-only
`models3d.generate` is checked when registered; three representative disabled drafts
cannot be enabled, run, or step tested; no run is persisted and the authenticated
user’s credit balance is unchanged. Its coordinator receipt is recorded on the
Task after execution.

These checks prove structural authoring and the tested normalization/guard
contracts. They do not replace live provider compatibility or natural-language
intent evaluation. Re-enabling queued skills requires waiting/resuming on the
completed result, cancellation/error handling, workflow-owned embeds, and exactly
one settlement owner. Approval-required skills need explicit per-run approval.
