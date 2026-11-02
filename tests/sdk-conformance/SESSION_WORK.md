# Cookie session work CRUD conformance

TASK-7993 adds direct Tasks and Projects namespaces to the npm/Python
SessionClient. Each named method calls SessionBridge and the typed Rust SDK work
service. No CLI launch, saved-profile discovery, generic HTTP endpoint, or
independent encryption implementation participates.

## Public calls

npm exposes `client.tasks` and `client.projects`, each with async
`list(filters)`, `show(id, filters)`, `create(input, filters)`,
`update(id, patch, filters)`, and `delete(id, {confirmed: true}, filters)`.
Input options use camelCase; decrypted output retains the shared Rust service's
snake_case wire field names. Unknown input fields and duplicate camelCase/wire
aliases reject before transport.

Python exposes the same namespaces and named async operations, with snake_case
TypedDict inputs and keyword-only `filters=`. Delete additionally requires
keyword-only `confirmed=True`. Python 3.10 remains supported without an added
typing dependency.

Every operation requires either Personal (`personal: true`) or an explicit
Team ID. An ambient Team never supplies this choice. Project creation requires
an explicit `always_ask` or `apply_and_show` policy unless
`chat_organization_only` is selected, following the shared Rust service.
Ordinary user Task and Project private fields remain encrypted. Assigning a
Task to OpenMates AI follows the shared SDK private-operation consent policy;
the fixture denies that inference-capable path before any request.

Rust SessionBridge exposes corresponding typed `tasks_*` and `projects_*`
methods, taking shared Rust DTOs. Foreign bindings decode bounded JSON into
these same strict DTOs. There is no arbitrary route or untyped HTTP escape hatch.

## Synthetic proof

Capability: `session.work-crud.v1`.
Fixture: `fixtures/session-work.json`.
SHA256: `b180cccef9643b91a13cd74030d2ac66246d57cc28bb252a3d9a1787fa2ce421`.

One test-only peer, `session_work_server.py`, binds ephemeral IPv4 loopback and
serves all three actual libraries. It independently decrypts their request
ciphertexts with the public synthetic master/Team keys from
`project-create.json`. Test adapters may start this peer; SDK runtime code
never starts a helper process.

The ten vectors cover Personal/Team CRUD for both families and six boundary
cases: unknown/routing inputs, unconfirmed deletion, missing/contradictory scope,
private-inference/write-policy refusal, closed client, and queued cancellation.
The peer checks cookie-only transport and language identity, each rotated cookie
on the following request, encrypted private content, Team wrapper scope, object
key separation, canonical Project default focus, nullable Task due date clearing,
Task versioned writes, exact Project deletion confirmation, and empty lists after
deletion. Credential exports must contain the final rotated cookie and a newer
revision. Invalid/closed cases require zero HTTP requests. The cancellation case
holds an active GET, queues another operation, cancels, and requires both callers
to reject with typed `cancelled`. Its shared `expected_first_error` oracle is
validated as `cancelled` by every adapter. The active HTTP response still finishes
and rotates credentials; the queued operation makes no request, and a fresh
operation succeeds. No canceled caller receives its settled private result.

Cancellation admission is bounded to 32 queued/active work operations. Work
requests finish their serialized transaction even when a foreign Future is
abandoned; cancellation does not drop an ambiguously committed HTTP future or
credential rotation. This development session bridge retains operation admission
and wiping output through the final caller-side lifecycle fence: canceled
workspace calls reject even if HTTP completed. Identity epoch checks prevent
queued work from running and completed private results from returning after
successful session import/login or logout. These security corrections do not
change the published API-key SDK contract. Rust unit tests
exercise queued cancellation, identity fencing, size limits and strict DTOs.

Fixed adapters:

- `node --experimental-strip-types tests/sdk-conformance/runners/session-work.mjs --fixture tests/sdk-conformance/fixtures/session-work.json --capability session.work-crud.v1`
- `python3 tests/sdk-conformance/runners/session-work.py --fixture tests/sdk-conformance/fixtures/session-work.json --capability session.work-crud.v1`
- `cargo run --manifest-path packages/openmates-session-bindings/Cargo.toml --example session-work-conformance --locked --quiet -- --fixture tests/sdk-conformance/fixtures/session-work.json --capability session.work-crud.v1`

Use a Python interpreter containing fixture-only cryptography dependencies via
`OPENMATES_SDK_CONFORMANCE_PYTHON` for the npm/Rust peer launcher.

## Limits

This proves a bounded synthetic cookie-auth CRUD slice. It does not prove live
backend/account compatibility, all selector/conflict/pagination/reference cases,
AI execution, all foreign-language cancellation timings, Plans or Workflows
session namespaces, all Rust work operations, or native artifact portability.
API-key SDK public behavior is preserved. Broad SDK family and publication
gates remain qualified by the maintained capability matrix.
