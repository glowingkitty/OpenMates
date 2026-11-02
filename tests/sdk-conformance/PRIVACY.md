# Bounded local privacy fixture

`local.privacy.v1` is a stateless subset, separate from the incomplete
`sdk.privacy-policy` family. Its 39 shared synthetic vectors are registered in
the maintained capability matrix and fixed conformance adapter map. Registration
and mocked gate checks do not establish that any real SDK adapter has passed.

The Rust runner calls public `openmates_sdk::privacy::prepare_local` and
`restore_local` directly. It uses neither a foreign binding nor the CLI as an
oracle. npm calls exported `preparePrivacy`/`restorePrivacy`; Python calls
exported `prepare_privacy`/`restore_privacy`. The latter two use their own native
facades, so their actual conformance run requires freshly built matching NAPI
and PyO3 artifacts. The SDK runtime never launches these tooling runners.

The shared fixture covers known-mapping reuse and metadata, longest matches,
fresh repeated-email masking, Unicode memory values, disabled categories/master
detection, shielding existing tokens, one-pass literal restoration, unavailable
and conflicting mappings, malformed mapping filtering and explicit enhanced
detection refusal. Six compact expansion vectors check exact and over-limit
UTF-8 text, mapping count and canonical JSON input bounds. Further cases check
generated restoration budgets, canonical numeric spellings and repeated-token
or long-placeholder output expansion at and beyond the supported limits.

Current limits are 1 MiB UTF-8 text, 4 MiB canonical JSON operation and 1,024
combined memories/existing mappings for preparation (or mappings for restoration).
Prepared and restored text are each capped at 1 MiB before appending output.
Preparation also checks that its generated text and mappings fit restoration
input budgets. The canonical JSON budget normalizes numeric values as finite
IEEE-754 values, with either zero sign encoded as `0.0`; foreign JSON spelling
does not define this budget. A separate 16 MiB raw foreign transport limit
bounds decoding. The checked public facades validate typed JSON, nesting and
number boundaries; these 39 vectors do not exhaust every host-language input shape.

Random placeholder values are not compared across processes. Each adapter checks
their opaque token structure, uniqueness, replacement and local round trip
against independently specified expected mapping values. Deterministic cases
check exact outputs. Errors must be typed `invalid_argument`; silently skipping
a vector, changing the fixture digest or returning unsupported fails the gate.

All three adapters receive the same `--fixture` and `--capability` arguments.
Thirty-nine cases would add 117 vector executions to a complete three-language
run; source registration must not be added to historical successful totals.
No account, network, credential discovery, SDK profile, model or provider is used.
Enhanced anonymization, complete session/stream privacy-policy integration,
backend behavior and platform packaging remain broader explicit gaps.
