# Isolated component visual smoke

The existing four-job GitHub coordinator supports `visual-smoke` capture for up
to two default public component fixtures. The immutable request binds the source
commit and exact URLs; the dispatch receipt separately identifies the harness.
Backend, CMS, database and built frontend run on the hosted runner. Backend
networking is internal; shared-dev addresses remain rejected. No AI worker,
provider credentials, shared test accounts or paid execution modes are enabled.
Authenticated application-route smoke is outside this bounded preview mode.

After the assigned task's prerequisite decision, submit through the canonical
checkout (replace SOURCE_SHA with its full reviewed immutable commit):

```sh
python3 scripts/ci_coordinator.py submit --session daba --source SOURCE_SHA \
  --mode visual-smoke \
  --preview-url 'http://localhost:5173/dev/preview/tasks/TaskDetailFullscreen?chrome=0' \
  --preview-url 'http://localhost:5173/dev/preview/tasks/TaskActivity?chrome=0'
python3 scripts/ci_coordinator.py status REQUEST_ID
python3 scripts/ci_coordinator.py result REQUEST_ID
```

The runner invokes the candidate's unchanged `visual-smoke.mjs`. Both canonical
script viewports (laptop 1440×1000, mobile 390×844) are retained in
`ci-visual-smoke/`, including `summary.json`, PNGs and a hash-bound `receipt.json`.
The ordinary result binds source/harness/run identity, frontend/API locality,
shared-dev rejection and cleanup. A script error or incomplete output fails the
job; no assertion is skipped to produce successful capture.

`review_status: pending` means **assigned-agent screenshot inspection pending**,
not a new mandatory human approval. Download via the supported result command,
inspect every PNG, and use the existing `sessions.py visual-smoke` evidence
workflow with the exact receipt/screenshots and `Defects:` / `Accepted differences:`
summary. Record passed only after inspection, failed for objective defects, and
ask the user only about unclear design intent or existing confirmation gates.
The capture receipt remains immutable; reviewed evidence is a separate existing
session record. No runner-generated review summary can substitute for inspection.

Task capture must not be dispatched before its badge outcome. This mode does not
activate the pending queued hold/supersede control or private CI candidate.
