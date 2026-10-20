# Expanded transcript correction evaluation — 20 October 2026

This evaluation concerns transcript **correction**, not summarization. Mercury
was faster overall, but the bank does **not** clear the predeclared gate of no
unexplained critical Mercury regression. Keep proposed additional automatic
defaults held; any narrower eligibility requires a separate supported decision.
This evaluation did not change the shared runtime or routing defaults.

## Fixed method and identity

The new bank contains 24 synthetic multi-speaker recordings: twelve German and
twelve English, 164–777 words each, 7,628 source words total. Every scenario was
run twice against direct Inception Mercury 3 LOW and direct Google AI Studio
Gemini 3.8 Flash LOW: **96 native completions**, representing 24 new scenarios,
not 96 independent cases. The earlier six short corrections are excluded.

Cases cover corrected amounts, currency, names, dates and owners; formal and
informal German, code-switching, exact Unicode identifiers/paths, uncertainty,
negations, quoted untrusted instructions, and omitted documentation versus new
actions. All requests used the exact production shared correction prompt and
forced `finalize_transcript` tool. Case inputs and finite checks were frozen
before inference under the [agreed evaluation protocol](expanded-evaluation-protocol.md).

- Published benchmark/case revision: `6de23b1a18421485ead5ad592bb1accd7e2804b8`.
- Case module SHA-256: `ed78f52103cb7ae8b315b24eed7f14044a9503b8d9dbfd55b3937fc381f5ec67`.
- Fast harness SHA-256: `f02fff6bb33eb4e2addb4bc4300ca6f19aaa2144a6d05be38a98937b4c6eef0a`.
- Actual runtime: `b2a15b4d7055c18b22026e6e086fa5919e3337c2`.
- API image: `sha256:1eb8eb5a49e21acc8f8d38663742a1a65d9fa539540e456da4e6e4253eae84d6`.

The exact published case module and then harness were loaded in a disposable API
Python process under a renewable shared read lease. Loaded production prompt and
SecretsManager sources matched the publication; imported shared reporting helpers
matched exact function-source hashes. The sidecar distinguishes published code
executed in memory from files in the shared runtime. No accounts, chats, tasks,
ASR output, defaults or shared service files were changed.

One rejected startup made **zero provider calls**: an interpreter-dependent AST
comparison falsely rejected an identical shared helper. Its error and matching
published/API helper source hashes are retained separately. The temporary runner
then compared exact function text, preserving all production dependency guards.
No inference request was retried or added to the 96-call run. Raw report and
identity were copied to private storage before releasing the lease, after which
the separate workflow benchmark could start.

## Native results and timing

All 96 calls were available, with no HTTP 429s, retries, model fallbacks,
truncation or wrong tools. Actual observed models were `mercury-3` on all 48
Mercury calls and `gemini-3.8-flash` on all 48 Google calls. Terminal finishes were
verified: Mercury reported `stop` 46 times and `tool_calls` twice; Google reported
`STOP` 48 times. Input/output usage was present and passed counter checks on all
calls.

| Measure | Mercury LOW | Gemini 3.8 Flash LOW |
|---|---:|---:|
| Strict finite checks, all | 46/48 | 44/48 |
| Strict finite checks, German | 23/24 | 23/24 |
| Strict finite checks, English | 23/24 | 21/24 |
| Complete latency median | 2.308 s | 4.393 s |
| German complete median | 2.480 s | 4.720 s |
| English complete median | 2.042 s | 3.742 s |
| Complete latency p95, nearest rank | 6.651 s | 7.386 s |
| Complete latency maximum | 10.917 s | 7.511 s |
| Complete calls over five seconds | 6/48 | 17/48 |
| German calls over five seconds | 4/24 | 11/24 |
| English calls over five seconds | 2/24 | 6/24 |
| Strict passes within observed five seconds | 41/48 | 29/48 |

The six slow Mercury completions remain in all quality denominators. They fail
the five-second screening condition even when their text is correct; they do not
count as evidence of a successful production primary correction under that
deadline. This harness streams, while the actual correction helpers are
nonstreaming. Even a streamed result under five seconds is not proof of the
production helper's complete latency.

All authored-text TTFT values were null because responses carried the correction
in tool arguments. First tool-argument medians were 1.346 s for Mercury and
4.378 s for Google. Mercury can emit partial argument fragments; Google commonly
emits an entire tool object. Neither metric is completed-correction latency or
ordinary text TTFT.

Strict paired results, per scenario/repeat:

| Pair result | All 48 pairs | German 24 | English 24 |
|---|---:|---:|---:|
| Both pass | 43 | 22 | 21 |
| Only Mercury fails | 1 | 1 | 0 |
| Only Google fails | 3 | 1 | 2 |
| Both fail | 1 | 0 | 1 |

These are immutable finite-check verdicts. Manual fidelity review is recorded
separately and must not treat equivalent wording or a regex miss as an automatic
critical defect.

## Complete manual fidelity review

Every corrected transcript and title was inspected against its frozen source,
including speaker attribution and all edits to the shared/long background. One
reviewer covered all 48 German outputs; an independent reviewer covered all 48
English outputs. Critical fidelity, functional validity, timeout and minor
language/title/cleanup findings remain separate in the per-output receipts.

| Manual result | Mercury LOW | Gemini 3.8 Flash LOW |
|---|---:|---:|
| No critical fidelity defect, all | 46/48 | 45/48 |
| No critical fidelity defect, German | 23/24 | 23/24 |
| No critical fidelity defect, English | 23/24 | 22/24 |
| Valid complete tool result | 48/48 | 48/48 |
| Critical+functional pass within observed five seconds | 41/48 | 30/48 |

Manual critical pairs were: **44 both pass, one Mercury-only failure, two
Google-only failures, one both fail**. German pairs were 22 both pass, one
Mercury-only failure and one Google-only failure. English pairs were 22 both pass,
one Google-only failure and one both fail. A baseline defect does not excuse a
Mercury defect under the agreed gate.

Concrete critical findings (repeat numbers are the receipt's zero-based values):

- German privacy, Mercury repeat 1: changed literal identifier `TEST-ä72` to
  `TEST-A72` and capitalized case-sensitive filename `veröffentlichung_Entwurf_v2`
  to `Veröffentlichung_Entwurf_v2`. Google preserved both in that paired repeat.
- German privacy, Google repeat 0: changed the filename to
  `Veroeffentlichung_Entwurf_v2`. Transliteration is not equivalent for a literal
  Unicode filename.
- English ownership: Mercury repeat 1 and Google repeats 0 and 1 changed owner
  `Mateo` to `Matteo`. The case-specific source names Mateo; the shared background
  contains Matteo. Normalization toward the background changes the source's
  named checker without authorization.

One strict failure was a false positive: Google English timezone/name repeat 1
said “do not leave **a** voicemail,” preserving the source restriction while the
regex expected “do not leave voicemail.” Its manual fidelity pass is recorded
alongside the unchanged strict failure. Mercury filename capitalization was an
additional critical change the case-insensitive regex missed in an already
failing row. No case or oracle was changed after inspecting outputs.

Mercury frequently retained abandoned spoken self-corrections, such as the old
amount followed by “richtig ist,” or both the original and corrected owner
assignment. The final intended value remained clear in those rows, so this was
recorded as incomplete cleanup rather than a changed final fact. Both arms
sometimes generated generic titles focused on the shared note-taking context.
Formatting changes and removing redundant same-speaker labels were not treated
as attribution failures. Neither arm executed the quoted untrusted instructions
or invented a created task in this bank.

## Cache and interpretation limits

Mercury reported **19,265 cached prompt tokens out of 49,811 (38.7%)**, with a
positive cache counter on all 48 calls. Google supplied no cached-token counter
on these calls; its cache reuse is unknown, not proven zero. Repeated source
context, paired repeats and provider-side prefix caching confound warm latency.
No cold-cache or invoice-cost claim follows from this experiment.

Native Mercury completion usage totaled 48,880 tokens, with 46,575 in its
reported reasoning subset. Google reported 26,210 output-plus-thought tokens,
including 3,340 thought tokens. Native counters are preserved without subtracting
reasoning to infer authored correction tokens. The harness's fixed-rate nominal
cost estimates do not include cache discounts and are not supplier invoices.

The sample cannot establish a population error rate. Shared background text and
repeats are not independent observations. The longest source is 777 words, so
this does not establish behavior for 1,500-word or unbounded recordings. ASR,
browser/CLI delivery, automatic fallback behavior and production nonstreaming
latency were outside this direct-provider comparison.

Private artifacts are intentionally uncommitted under canonical
`logs/mercury-fast-inference/acad-2026-10-20/`: the raw
`mercury-acad-expanded-correction.json`, `-runtime.json`, `-statistics.json`,
`-startup-rejected.json`, `-german-review.json`, `-english-review.json`, and the
combined `-manual-review.json` / `.md` with all 96 reviewed rows.
