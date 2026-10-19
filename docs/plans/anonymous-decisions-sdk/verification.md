# Implementation verification

Status: implementation verified. Dev rollout receipts are recorded in the linked Task.
Task: `44295141-a609-4fb4-808a-9db65edc44f3`. Session: `b005`.

Initial dev rollout: `a9afdd19422862aed0fdce36453f5ae581a5c0a1`, with the
architecture documentation follow-up `7afcd038e3e46f8df58bdc123cfd1fcf1351277b`.
The API and AI worker were healthy on the feature commit; both localized article
URLs and the latest website deployment were verified.

## Scope and approvals

The user approved the original ai.decide and SDK reviews on 2026-10-19, requested
Jev 1.14 and image processing, then explicitly approved the updated image review:

- `feature.app-skill.ai-decide@1`:
  `8ceb673f123250c22db2091d17d386a2391359dbacf5c70a4f55152a3c77815a`.
- `surface.sdk@1`:
  `a197b59d5b56ef8ba6fcb2f2ef68ecb9d5d440a9254b19784966d544765f0f3c`.

Approval receipts are recorded through `specifications.py approve` for b005.

## Local checks

Initial backend, Jev transport, anonymous metering and Python SDK checks passed
226 cases on 2026-10-16, excluding one existing unrelated app-classification case.
Image transport, validation and middleware regression checks extend those cases;
the final run receipt is recorded in the Task activity and execution-host logs.

The image-aware CLI and TypeScript SDK suite passed 17 tests. Python anonymous
SDK coverage passed 70 tests. Publication manifest/localized slug coverage passed
10 tests; the English/German rendered privacy disclosure passed its focused test.
Targeted ESLint, snippet syntax checks and CLI JavaScript bundling passed.
Full package declaration/type checking remains affected by pre-existing
cross-package/UI diagnostics; changed SDK entry points had no diagnostics.

App metadata, locale files, generated SDK methods and Specification artifacts
are regenerated through their normal generators. Local checks do not establish
successful product E2E execution.

## Isolated CI and live verification

- Focused backend CI passed 118 tests and Python anonymous SDK CI passed 70 tests
  on source `df0935b3b41e386580e50120cc711d811bdf5877`.
- Final `website-public-routes.spec.ts` browser CI run `39241850107` passed all
  15 tests with zero retries and zero skips on source
  `942903c0e53b7eff184c1af76d50595d500e6ce6`. Preserve its selected recording.
- Source identity checks show that the final website product subtrees and exact
  browser spec match that passing browser source. The Python SDK subtree matches
  its passing source. Owned backend files except `ask_skill.py` match the backend
  CI source; the upstream streaming-context fix and our quota denial were merged
  in `ask_skill.py`, with 31 focused merged streaming/quota checks passing.
- The SDK parity gate recognizes the named `OpenMatesAnonymous` class. Its
  correction passed 17 focused CLI/npm tests and targeted ESLint.
- Generated SDK reference and test-coverage documentation is current. All four
  deployment SDK audits passed in the final merged source export: cleartext
  parity, cleartext boundary, documentation coverage, and test coverage. No
  product tests were repeated for the SDK class and generated-documentation
  gate corrections.
- The existing coverage policy holds `anonymous-cli-skill.spec.ts` under
  `official_cloud_eligibility_and_billing`: the portable self-host fixture returns
  404 for these cloud-only routes. Image and quota REST coverage is retained in
  that spec. No unrelated cloud-fixture infrastructure is introduced here.
- The article flow uses the existing standalone website fixture, which builds
  and serves `frontend/apps/website`. The older `public-publications.spec.ts`
  app-compatibility suite targets the Self Hosting Edition and returns 404 even
  for existing publication routes; its unrelated cases are left unchanged.
- Deploy the scoped candidate through the session helper after the supported
  checks, reporting the cloud REST E2E hold separately from passing checks.
- Real inference remains dev-only, using disposable guest identity and client
  state if the existing allowance admits it. Dev public status on 2026-10-19 is
  inactive; no budget configuration is changed for verification. Production
  inference/rollout and SDK package publication remain outside this task.

Do not treat a concise Plan validator structural pass as execution evidence.

## Baseline failures outside this feature

A read-only export of exact task base
`6ce7904afedf48a1785dac01090eddea5e0cca80` reproduced ten existing failures:
the missing anonymous classification on `business.search_trademarks`, the
Workflow planning-stop assertion, and eight Workflow Gemini tariff assertions.
The baseline run collected 16 tests with ten failures and six passes, with no
fixture/import errors. The authoritative JUnit and stdout receipts are
`/tmp/openmates-decide-baseline-zfyfslbi/baseline-verified-cwd.junit.xml` and
`/tmp/openmates-decide-baseline-zfyfslbi/baseline-verified-cwd.stdout.log`
on the execution host.
The separate Jev-settlement rejection test passed both baseline and current
standalone runs. These failures must not be reported as green feature checks or
fixed by changing unrelated billing or Workflow behavior in this task.

## Approved simplification and code-color follow-up (2026-10-19)

The user explicitly requested headerless guest REST with IP-based caps, simpler
SDK/REST examples in both languages, and code coloring matching the web app.
Existing approved billing, decision and publication contracts remain unchanged.
No allowance configuration, account access or durable guest capability changes.

Guest skill/chat requests derive a stable server-only IP identity when a caller
omits an ID. Optional existing client identities remain compatible. The same
IP/global daily, weekly and monthly ledger, conservative reservation and
settlement enforce admission. Headerless public status keeps its personal
percentage null while enforcing the IP cap. Account routes retain their existing
authentication, scope and billing rules. Counter data uses HMAC values rather
than raw IPs or content. Shared school Wi-Fi may share the IP allowance.

Status/availability and skill/chat use independent IP-backed minute counters
(60 and 20 respectively). Actual-handler coverage proves that 25 status polls
preserve all 20 execution admissions, rotating caller IDs cannot bypass the IP
limit, and status check 61 is rejected independently. Quota refusals remain
HTTP 429 with signup_required; meter/provider failures stay distinct.

Canonical Caddy ignores caller XFF by default and forwards its transport peer to
the loopback-bound API/Uvicorn trusted-proxy chain. Guest handling ignores
X-Real-IP, uses a public socket peer directly, and permits only one valid managed
XFF address from a private proxy peer. Malformed chains retain a stable peer or
unknown cap. Infrastructure configuration is unchanged; live production proxy
parity was not inspected.

Both localized articles now use default SDK constructors and header-free curl
examples. SSR highlighting uses the web app light/dark palette for TypeScript,
Python, shell and JSON; unknown code stays escaped and long lines scroll inside
code blocks. The account-free component fixture retains all four light/dark
phone/laptop checkpoint frames and proof metadata; visual review passed.

Final verification:

- Isolated backend CI run `39252303460` passed all 180 selected checks on source
  `f8b02b93d118f49f21b925a34e60a022a07f0183`, including image quote/dispatch and
  independent IP rate-bucket regressions.
- Component CI run `39252298026` passed both phone/laptop cases on that source,
  with no retries or skips. Its selected recordings uploaded successfully.
- Website route CI run `39251774253` passed all 15 tests with no retries/skips on
  source `9e23fb1885d9e87628a0c032596cd61b03424981`. It verifies localized slugs,
  default SDK constructors, header-free REST examples and computed syntax colors.
  Backend, component and publication rendering files remain byte-identical to
  their passing source. A later concurrent website redirect fix and its startup
  helper/test changes are preserved in the final integration; the combined
  website source is checked separately below.
- Local anonymous route/budget checks passed 116 cases with one known unrelated
  app-classification case excluded. Image checks passed 36 cases; renderer safety
  and colors passed 15; publication routes/manifest passed 10. All 22 article
  snippets passed syntax checks. Targeted lint, CSS/TS/Svelte checks, coverage
  registration checks (10), and focused review passed.
- Generated assertion-index and approved Specification bundles are validated.
  The immutable patch contains only the 27 follow-up paths; existing feature
  work and unrelated upstream changes are preserved.

The existing official-cloud REST browser policy hold remains: its portable
self-host fixture cannot expose these cloud-only routes. The retained REST spec
is updated; focused API handler/budget checks pass in isolated CI. Real inference
is not exercised while the existing dev free budget is inactive. No budget
configuration, production rollout or SDK package publication is part of this
follow-up. Final deployment readiness and selected evidence delivery are recorded
in the linked Task and chat.

Combined-source integration preserves upstream `02f835674358f624024a7c8bd73cfc48b22b004f`
without overwriting website helpers, redirects or coverage registrations. Source
`18053b9ec6c44570bc3d9d89d72af0f19a97efa4` contains the merged website suite;
isolated browser CI run `39253903256` passed all 15 checks without retries or
skips on this merged source. All backend, component and publication
rendering code still matches the successful `f8b02b93` candidate exactly.
