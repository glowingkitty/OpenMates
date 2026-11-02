# SDK conformance tooling

Shared fixtures contain synthetic public values only. Each language runner calls
its actual library, uses fake transport, and returns assertion IDs plus the SHA256
of the exact fixture bytes. Unsupported cases and exceptions fail the process.

Run one language/case, for example:

```sh
node tests/sdk-conformance/runners/npm.mjs --fixture tests/sdk-conformance/fixtures/core.json --capability crypto.aes-gcm-combined.v1
python3 tests/sdk-conformance/runners/python.py --fixture tests/sdk-conformance/fixtures/core.json --capability crypto.aes-gcm-combined.v1
```

Node 22 supports the source runner; install npm workspace dependencies and the
Python package's declared dependencies first. No product server or CLI executable
is involved. The npm source loader is development tooling, not an SDK dependency.

`inventory.py` emits public API strings for all three languages by source scanning.
The npm compiler scanner follows actual public barrels and resolves nested facade
types, including aliases/intersections; Python scans package modules and resolves
facade classes, exported aliases and existing dynamic context/activity facades.
Constructors are represented by class symbols. Type-only/private helpers and
external primitive members are excluded. Both class spellings and facade aliases
are retained, so symbol counts are not capability counts.

`test_inventory.py` proves new public modules, methods and nested facade methods
cannot silently evade inventory. `scripts/check_sdk_conformance.py` compares the
fresh scan with `config/sdk-capabilities.json`, checks exact generated binding
sources, and runs implemented shared cases. Strict release requires all tracked
capability families to meet its evidence requirements; the existence of a runner
does not complete untested families.

`session.project-items.v1` uses eleven shared encrypted Personal/Team vectors
through actual Rust, NAPI and PyO3 session clients. The fixed gate adapters check
projection, confirmed link-only deletion, refusal boundaries, credential rotation
and cancellation against `fixtures/session-project-items.json`. The matrix keeps
actual backend, complete-family and platform gaps open even when this subset
passes.

`local.task-order.v1` exercises the same stateless Rust ICU comparator through
Rust, npm and Python using 22 shared vectors. Callers supply a locale explicitly;
SDKs never discover the CLI profile or host locale. Stable finite-number position
and canonical title ordering preserve the original caller rows and metadata.
The fixture records its qualified Node24 oracle and differing ICU data versions;
it does not promise equality across arbitrary collator versions or malformed
UTF-16. The native TUI and human board use this policy for presentation while
CLI structured output and transport pagination retain wire order.

`local.privacy.v1` registers 39 bounded stateless masking/restoration vectors
against direct public Rust APIs and the public npm/Python native facades.
Random token values use structural/round-trip assertions rather than token
equality across processes. Exact/over-limit cases use compact deterministic
expansions. The [local privacy contract](PRIVACY.md) describes the inputs, limits,
typed refusals and remaining broad privacy-policy gaps. Registration adds three
fixed adapters, not evidence that those adapters have executed successfully.
