# Keyless trademark search and brand naming verification

The approved contract is `feature.app-skill.trademark-search@1`, fingerprint
`3340d27a84f0015edbf55ea30b0c27fc7eb18a97c276464ef16a669f088946d8`.
The user approved completing the keyless implementation first on 2026-10-12.
The approved bundle was not changed during implementation.

## Delivered behavior

Business `search_trademarks` accepts names, explicit regions, matching mode,
optional Nice classes, active-only filtering and a bounded result limit. The US
route uses the free, keyless USPTO website search endpoint. EU, Germany and
worldwide selections return explicit unsupported coverage and official manual
search links. EUIPO credentials and its integration are deferred. A failed search
is distinct from a successful zero-result search; mixed coverage retains useful
US results. There is no proxy, CAPTCHA bypass or paid provider fallback.

The web preview and fullscreen preserve query, filters, checked time, coverage,
truncation and official record links, including when saved and reloaded. Zero
results and provider errors remain visible. The official source-link allowlist
rejects credentials, unexpected ports and lookalike domains.

Business `find_brand_name` activates from “Help me find a name for my new product.”
It asks a compact intake, offers six to eight unchecked names and checks only two
or three selected finalists. It uses inline prose and bounded initial trademark
results rather than producing a document or researching every candidate.

## Verification

- Live USPTO exact, spelling-similar, class-filtered and zero-result probes passed.
- Provider, request, coverage, error and actual inference argument-dispatch tests:
  27 passed in isolated pytest CI. The preview contract check also passed locally.
- UI normalization and source-link validation: 27 passed locally.
- REST authentication, CLI, npm SDK, pip SDK and focus catalog: five isolated CI
  cases passed ([run](https://github.com/glowingkitty/OpenMates/actions/runs/38243642350)).
- Responsive preview/fullscreen, true-zero and unsupported-state component cases:
  four passed ([run](https://github.com/glowingkitty/OpenMates/actions/runs/38248206781)).
- Real region selector, provider response, saved preview/fullscreen and reload:
  passed ([run](https://github.com/glowingkitty/OpenMates/actions/runs/38249661646)).
- CLI text-phase regression and trademark error presentation: six focused tests
  passed; CLI TypeScript build passed.
- Real dev inference used an isolated disposable account and CLI state under a
  coordinated runtime lease. The successful conversation had a 26-word intake,
  seven one-line unchecked names and two selected finalists, Equafy and Cadenceo.
  Domain, web and actual US trademark embeds were retained. The live verifier
  passed. Both domains were unavailable, and the comparison correctly described
  truncated trademark evidence without claiming exact-name absence or clearance.

Real conversations also exposed and corrected split trademark array arguments,
JSON intake, an unnecessary spreadsheet, unsupported exact-absence claims,
introductory-price budget reasoning and duplicated or missing CLI response phases.
A further available-domain check rejected renewals above the annual budget, but
estimated unchecked registrar prices. The final 323-word prompt requires tool-quoted
prices and ignores earlier assistant estimates. A fresh real conversation then
used a 19-word intake and seven unchecked names. It correctly rejected Stillsum's
quoted renewal above the annual budget, rejected unavailable Solofloat, and gave
no unchecked registrar price amounts. Its finalist turn exposed a separate tool
admission omission: preprocessing offered Hosting and Web but omitted Business.
A narrow active-naming companion rule now offers the three available finalist
checks together while preserving exact skill requests, tool-free intake and
normal availability/mate boundaries. Twelve focused regressions passed locally and
in isolated CI ([run](https://github.com/glowingkitty/OpenMates/actions/runs/38293239495)).
The subsequent deployment gate passed all 95 selected tests. Its prompt-only test
harness also received the enclosing setup-timing helper introduced by the shared
inference update; its original focus assertions were preserved.

Final source-link cleanup exposed another CLI replacement case: Markdown link
destinations changed while the visible labels and comparison stayed the same.
The CLI now compares a conservative visible-label projection, mapping appended
text back to its original Markdown offsets. It preserves changed/shorter focus
phases and partial Markdown. Focused regressions cover the actual cleanup pattern,
appended prose and phase resets.

A fresh held-out three-turn conversation on the final deployed source passed the
live verifier: exact trigger phrase, automatic activation, 26-word plain intake,
seven one-line unchecked candidates, and only Stillsum/Tidely researched. It made
two domain calls, two web searches and one batched US trademark call, capped at
five records per name. The 112-word comparison displayed once, rejected Stillsum's
quoted renewal above the annual budget, identified the existing Tidely platform,
and explicitly stated that only returned records were reviewed, exact-name
absence remained unconfirmed, and the checks were preliminary. It produced no
document or spreadsheet and no unsupported registrar price estimates. The prompt
asks for under 100 words; the observed 112-word comparison stays concise but its
word target is an instruction rather than a server-enforced limit.

Final behavior is deployed at `7f66a8a38651dc2fc4891d04b4a34cfc39535608`.
Coordinated runtime operation `docker-b2dd1796` restored all 17 services healthy.
The disposable fixture exhausted its credits before one retry; a normal
mailbox-bound development gift redemption replenished only that fixture, then
the fresh flow passed. The failed credit-limit recording is retained too.

## Public example admission

`find-brand-name-and-domain` was generated from the successful real three-turn
conversation, with six messages, 28 original embeds and original priced usage
metadata. All 21 locales are complete. The scaffold's 22 unit tests and translation
validation passed. Example metadata links both the trademark skill and naming
focus mode in the app store. Both dedicated phone and laptop browser cases passed
([run](https://github.com/glowingkitty/OpenMates/actions/runs/38285380244)). The
deployed example returned HTTP 200 and passed read-only phone/laptop inspection:
activation, all three app fullscreens, saved reload, official trademark record
links and both app-store example cards. Screenshots were reviewed at both sizes.

The first dedicated example run rendered the activation summary correctly, but
its test expected the inner activation bar before opening the now-collapsed
assistant activity group. The test now opens the real activity controls and still
requires the exact focus ID, trademark preview, fullscreen records and app-store
cards. A later test correction opens the skill's information view before asserting
its example card. Failed viewport attempts and retries are retained. Deployed
inspection retries corrected inspection-only assumptions about the close button
and links in grouped Hosting/Web views; all eight inspection recordings are retained.

The broader existing `example-chats-load.spec.ts` run had six passes, eight failures
and one skip. Failures concern other examples' collapsed activity controls, legacy
message/settings selectors and an edge-fade expectation. They were not repaired
as part of this naming feature; the dedicated naming browser admission is green.

An intervening shared routing-worker deployment exposed a runtime overlay omission:
the worker consumed `/translations` but was absent from the immutable overlay's
service inventory. The minimum correction adds that worker and advances the
artifact layout to v3, preserving v2 artifacts. All 12 focused tooling checks pass
against the current rendered Compose configuration. Coordinated recovery restored
all 17 services. The same upstream inference update exposed a pinned google-genai
1.58.0 custom-aiohttp constructor omission. A minimum compatibility guard preserves
the traced loop-owned session and initializes its missing request-args slot. A real
local aiohttp SSE test proves two streaming calls, session/TCP reuse and trace
callbacks with that exact SDK; it passed locally and in isolated CI
([run](https://github.com/glowingkitty/OpenMates/actions/runs/38285073584)). Real
Gemini inference resumed after the repair.

The generic existing clone spec requires live inference credentials; isolated CI
admission held it before execution because its paid-provider credential/spending
profile is unavailable. It was not weakened or replayed. The changed example has
dedicated static browser coverage and the scaffold adapter has a regression test.

All retained CI and real CLI recordings, including failures and retries, are
uploaded for delivery in the final task response. Early API runs produced no clip
because capture was disabled or the recorder executable was unavailable; later
successful parity runs contain the required CLI capture. Uploading retained clips
does not rerun tests. A pre-existing CLI WebSocket listener warning remains outside
this feature's scope. The final delivery inventory contains 54 distinct CI videos,
23 real conversation clips and eight deployed inspection recordings, including
inspection-only failed assertions and retries. Evidence upload commands were
also executed for pytest runs, which have no expected video capture.

## Follow-up: Workflow compatibility

On 2026-10-13, the Workflow adapter was found to retain trademark fields only
inside `raw`, despite advertising typed top-level outputs. A scoped passthrough
entry now preserves `matches`, `coverage`, `result_count`, regions, class/status
and matching filters, `partial` and the legal limitation. It keeps the original
response and whole-response embed behavior intact.

All three focused schema/normalization cases pass locally: partial coverage,
completed zero matches and unsupported-only errors. Changed-file Python and
TypeScript ESLint checks pass. Local test TypeScript checking was unavailable
because the tests' `tsc` executable is absent; the isolated candidate's web and
CLI builds pass.

The real keyless Workflow E2E passed in 38.7 seconds with no skips or retries
([run](https://github.com/glowingkitty/OpenMates/actions/runs/38368073066),
source `27d1757478938769c185b9f507664e7ff773576a`). A fresh isolated owner created
a disabled manual Workflow, step-tested a real ADIDAS class-25 search, ran it,
read typed downstream counts and partial flags, distinguished a unique empty
US search from unsupported EU coverage, and queued a report delivery. The test
does not claim owner-side receipt of the report. It retains an actual terminal
MP4 of the completed run and deletes the disposable Workflow.

Read-only review found no adapter defect. The approved Specification is unchanged.
EUIPO's free Trademark search API signup and Production approval steps are
documented for the deferred credentialed integration. DPMAconnectPlus has a
EUR 200 connection fee, and WIPO public database terms prohibit automated queries;
neither is recommended as a free automation signup.
