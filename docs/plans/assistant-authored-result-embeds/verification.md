# Verification in progress

The feature is not complete or released. The approved core and TV Specifications
remain authoritative; wiki is excluded.

## Backend and instruction checks

The full 25-kind backend snapshot passed 316 focused authored-result tests.
Coverage includes schema validation, selected-only instruction context, streaming,
ordinary encrypted identities, ownership, authorized image references, API child
hydration, and typed materialization. Subsequent committed fixture metadata checks
pass 16 tests. The isolated recovery-profile and bounded API diagnostic checks
pass 114 tests. The generated authoring registry passes 17 checks, and selected
encrypted media ownership and image proxy behavior pass 11 focused checks.

The current backend-first stage temporarily leaves TV frontend routes and component
paths unregistered in `backend/apps/tv/app.yml`. Restore the complete TV web metadata
with the components after the real CLI/SDK gate. The existing full-registration
unit assertion intentionally remains in place and must pass before completion.

## Isolated integration observations

- Source `fef1e0aa8fc32e061376b10a0ea023314756d8bc`, run `40308278538`:
  dependency preparation rejected TV web registrations without components.
  No test capture started.
- Backend-stage source `241efb6a5f7e1353c9c368bc34f88d0a5e24f908`, run
  `40309657655`, request
  `dfef5445382504d72b1682e7234f4840e46e851728118f465c68e514c8032bda`:
  the real backend materialized all 25 finished typed children and the carrier.
  CLI creation timed out, so neither SDK case ran. The isolated server remained at
  recovery epoch zero while saved-chat CLI completion required an epoch-one job.
  Registering this spec in the existing guarded marker-only recovery profile is
  the scoped correction. The profile registration was published as `7a47fbcd10db8ca3969f77a6a5508d0ed834be50`.

- Source `0f9ed75c34ba50dcf4d6829215e4db0ea012527e`, run `40316339031`,
  request `7bc0fc69fbffa6d7674cf841fe70e330d6c4bbda6c8e406f93dfe3608f3a8818`:
  the receipt confirms recovery epoch one. All typed records and the sealed
  response completed, but the CLI still timed out. No static wire mismatch or
  26-record pagination problem was established. The API log tail omits the
  terminal-publication interval. A bounded, test-only incoming-frame metadata
  trace is prepared; no further product fix is justified from these logs alone.

- Trace source `a28c5742684b4f3a9683533b357a46d38856b0d8`, run `40323910659`,
  request `4b15dee0db578ecdecd7bd2ee86a870b41954b54e70d2c318a4028c83ce971b9`:
  one CLI socket receives all 26 embed records and provisional updates. No
  terminal stream frame arrives. On retry, a recovery job reaches terminal state,
  then typed-output discovery reports failure. The next diagnostic uses the
  existing safe API exception summary to retain the underlying error location.
  The exact-case capture is published as
  `1e1e71d99e1e0f8afe7258a0c01500dc0c66cee6`; run `40330130790`, request
  `eeedf81b0767cf2dd2888533a2d130ce489fe2555db5ec79b4f9ccaf90284cef`,
  uses the same immutable product source with the expanded bounded capture.
  Both attempts fail with the explicit `embed_revision_conflict` CLI result.
  This run does receive completed output discovery and a terminal stream frame.
  The API exception summary contains only an unrelated DNS failure. Existing
  CLI persistence reconciles `embed_write_denied` by verifying and reusing the
  canonical head, but omits revision conflicts from that same path. The scoped
  correction adds that conflict to the existing guarded reconciliation without
  relaxing immutable ciphertext, identity, version, parent, or key checks.
  All 57 focused canonical reconciliation tests pass, including divergent
  content and identity rejection for both error codes. Integration is pending.
  Candidate `5954bcc72ed7ead5005b691f4c6e224525f75f96`, run `40333108313`,
  request `2a62cd299a5ab8fb7acbbeff692cfaeb89c33c9a2816b19a0f28161aeab6e6d9`,
  includes this correction and the registry/media groundwork. Specification
  preflight, Python compilation and changed-test metadata pass. A standalone
  CLI package typecheck is not green: it reports 221 errors across UI/Svelte
  imports and other files, with none in the changed CLI client. This is not a
  passing package typecheck or an established baseline comparison.
  The first CLI case passes the complete 25-kind lifecycle, cache clearing,
  reload, exact fresh reads and anonymous denial. The npm case then fails device
  approval: a newly paired receiver requires its own fresh TOTP verification.
  On serial retry the CLI completes but returns a provisional prefix without the
  fixture's final sentence. The matching recovery-job announcement resolves the
  collector before the final frame, and the already-terminal branch trusts that
  prefix. These failures remain failed integration evidence.

The subsequent correction distinguishes an authoritative final frame from a
recovery handoff. A handoff carries no provisional body; the already-terminal
path reads the exact authorized persisted assistant in a bounded fresh window.
The leased path retains verified sealed content. Empty/unreadable text and
identity mismatches fail closed, and late provisional updates cannot replace
final text. All 67 canonical-read/reconciliation tests, 54 collector tests and
four selected client recovery scenarios pass; scoped lint and metadata pass.
The SDK test now performs fresh verification before exact device approval.
Review found no remaining blocking issue in this scoped correction.

Candidate `beeaeba1a440a07721f7e151ccabf0dd379ab456`, run `40338782453`,
request `401e7adfc4926e018c5cc4e0ce2b07027b5eccb15fecab662c44c7d4d87f5e24`,
fails both CLI attempts by timeout before either SDK case runs. Both traces
receive typed records and provisional text, but no current final frame or
nonempty recovery-job offer. Retained logs do not prove the current cause;
the DNS exceptions belong to OpenObserve, not Directus.

An independently established final-fanout defect is corrected next: one device's
discovery exception cannot abort healthy peers. Final sends use bounded parallel
delivery with original-socket authorization checks and fail closed on discovery
or transport failure; nonfinal delivery remains serial. All 105 focused tests,
Ruff, metadata, compilation and review pass. Literal CI-only stages distinguish
listener receipt, discovery and final send. Fixture-only publication logs also
report Redis publish acceptance without changing its behavior. Their 26 fixture
checks pass; the bounded diagnostic exporter passes 119 checks and privacy review.
API-stage capture is published as `5511bf0680f7e2b5e7f2b622f6f761b7c1c650e9`;
the additional publication capture is published as
`de336c0749fc9a2732d38c554f2353efa6f4589e`.

Candidate `554345a4251e9e2efb7afdce098582d7672f3fc6`, run `40349451207`,
request `94d04dcfe62aec1198e4c062cb19297a181a7de4bc00913dbeea60ca811f8c3a`,
passes the full 25-kind CLI lifecycle and direct npm SDK reads. The Python SDK
case fails because `toon-format==0.9.0b1` decodes a bare empty array as the string
`"[]"`. The serial retry then fails typed-output discovery. Safe trace confirms
Redis accepted publication, the API received the final response, and job
discovery succeeded, but typed-output discovery failed for both devices before
final delivery. The fixed diagnostic did not yet identify the exception class;
this is not a passing complete suite.

The next bounded correction upgrades the official Python codec to 1.0.0 and
retains strict SDK comparisons. Six wire vectors distinguish empty arrays from
literal quoted strings and preserve source JSON. Five new regressions reproduce
under the old codec; 57 relevant SDK/key-wrapper/recovery checks pass with 1.0.0.
One broader pre-existing workflow skill test fails identically under both codec
versions and remains outside this change.

Typed discovery currently re-reads the same chat twice for each same-chat output.
The correction reuses the already-authorized root only within that output row;
all rows and subsequent requests still authorize freshly, and distinct target
chats retain independent checks. All 161 Directus operation tests pass. The
three-second Directus POST deadline is unchanged; the observed discovery failure
at approximately that interval does not yet prove its exception class. The
allowlisted diagnostic now retains HTTPX timeout/transport class names without
exception text. All 32 focused final-delivery tests and 119 diagnostic checks
pass. Independent review found no blocking issue. The safe transport-class
diagnostic is published as `bd81f9166aed34aad25b78356a83c942a270e6be`; product
integration remains pending.

The SDK cleartext parity, boundary, documentation and test-coverage audits pass.

The fixture now supplies validated committed postprocessing metadata, preventing
provider calls in this deterministic check. This change alone does not establish
that the delivery timeout is fixed. Existing failure artifacts are retained in the
coordinator result directory; select only the latest successful recording per flow
when successful evidence becomes available.

## Remaining proof

Prove real persisted CLI and SDK behavior, then default-routed live assistant
creation on the scoped deployed revision. The installed native preview supports
explicit isolated state and relevant partial commands, but actual behavior is
unverified. An unchanged private Rust SDK dependency from tested source
`33083b6d86100891bb09745b5f28b799672bee56` and a direct-library read harness
compiled with its original lock under the resource guards. The SDK remains
unpublished with its existing migration gaps. Live Rust reads remain unexecuted;
passing npm/Python reads are not Rust parity.

Web implementation, component checks, sharing/maps/calendar actions, landing
animation and the admitted real FOSDEM example remain outstanding. No Apple
completion is claimed.
