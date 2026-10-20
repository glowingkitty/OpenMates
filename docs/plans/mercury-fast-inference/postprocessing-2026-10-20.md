# Postprocessing comparison — 20 October 2026

Keep `google/gemini-3.5-flash-lite` as the postprocessing default. Native Mercury 3
LOW provided no meaningful overall latency advantage in this sample and produced
additional language and output-contract defects. This recommendation concerns
generative postprocessing only; it does not change Jev decisions or transcript
correction routing.

## Method and source identity

The opt-in `backend/scripts/benchmark_postprocessing_models.py` ran 40 sequential
native completions: six German and four English synthetic exchanges, two repeats,
both direct Inception Mercury 3 LOW and Google AI Studio Gemini 3.5 Flash Lite.
Model order rotated. There were no provider retries or model fallbacks.

The harness called the actual `handle_postprocessing` entry point with the full
`base_instructions.yml` postprocessing tool and production output normalization.
Bounded Jev decisions were frozen identically across arms; Jev quality was not
tested. Time was frozen. UI metadata translation was disabled so a second model
could not repair language mistakes. No account, chat, task or shared runtime was
modified. All inputs were synthetic and results stayed in memory until private
receipt writing.

- Published harness: `a7be2a23efa0e66ebf1e64ddf7cfc1d1b38ef71a`.
- Harness SHA-256: `1403c611a9a885f6cb0359223d5d27cf9e701871f8a7f8369a3ccf846bcce081`.
- Actual shared runtime revision: `b2a15b4d7055c18b22026e6e086fa5919e3337c2`.
- Actual API image: `sha256:1eb8eb5a49e21acc8f8d38663742a1a65d9fa539540e456da4e6e4253eae84d6`.

The exact published harness was loaded into a disposable Python process in the
existing API container under a renewable shared read lease. Loaded postprocessor,
base instructions, task/suggestion/learning helpers and `llm_utils` sources were
hashed and matched the published revision. The identity sidecar also records the
83 loaded backend source modules. Raw report and identity were copied out before
releasing the lease; both are mode 0600.

## Results

| Measure | Mercury 3 LOW | Gemini 3.5 Flash Lite |
|---|---:|---:|
| Native completions available | 20/20 | 20/20 |
| Observed model matches requested arm | 20/20 | 20/20 |
| Complete latency median | 1.590 s | 1.603 s |
| German latency median | 1.367 s | 1.661 s |
| English latency median | 1.956 s | 1.524 s |
| Strict finite-oracle passes | 8/20 | 12/20 |
| Summaries exceeding 20 words | 3 | 0 |
| Outputs with four rather than six normalized new-chat suggestions | 2 | 0 |
| Requested structured task proposals present | 0/4 | 1/4 |

There were no HTTP 429s or availability failures. Both arms reported input/output
usage for all calls. Mercury produced 12,497 completion tokens, including 3,343
reported reasoning tokens; Lite reported 6,676 candidate tokens. These are native
usage counters, not a billing comparison.

Manual inspection covered every title, summary, follow-up, new-chat suggestion and
task field in all 40 outputs. It found an English-language Mercury case with the
German title “Oskars Lissabon-Reiseplan,” which the finite language regex missed.
Mercury's shortened suggestion lists arose after production sanitization removed
short raw suggestions and balanced the two suggestion halves. Mercury also
claimed a task had been created in one summary despite returning no proposal.

Lite was imperfect too: one summary claimed task creation from a recommendation,
two summaries claimed a comparison had occurred when the exchange only restated
requirements, one German result introduced an unsupported Easter-egg explanation,
and some German suggestions had malformed verbs. One active cable follow-up
relaxed an 89-euro ceiling to “under 90 euros.” Both arms suggested departure
cities absent from the travel exchange. Neither arm followed the quoted untrusted
instruction or fabricated structured task updates.

Strict scores are not manual factuality scores. Several regex failures were false
positives: valid German noun-phrase summaries, “no tickets booked yet,” and “no
data loss confirmed.” Other flags merely detected omitted details in short
summaries. The private review preserves each original oracle flag alongside
per-output manual notes; no aggregate manual quality percentage is claimed.

## Cache observations and limits

Mercury reported **80,018 cached tokens out of 94,356 prompt tokens (84.8%)**,
with positive `cached_tokens` on **20/20** calls. Eighteen calls reported more than
1,000 cached tokens; two reported only nine. Lite reported 38,554 cached prompt
tokens across 19/20 calls. Requests added no explicit cache controls: these are
native reported automatic reuse counts. A long frozen shared prefix and repeated
cases favor caching, so this is not controlled cold/warm latency or billing proof.

The sample is small and synthetic, and one German “Boxen” case leaves storage
boxes versus speakers ambiguous. Translation repair and quick tips were disabled;
this is not an end-to-end user-chat benchmark. Task fields are optional in the
production tool, and both arms often omitted explicitly requested proposals.
The evidence supports keeping the current postprocessor rather than switching
defaults based on speed or these strict regex scores alone.

Private artifacts, intentionally uncommitted, are under
`logs/mercury-fast-inference/acad-2026-10-20/` in the canonical checkout:

- `mercury-acad-postprocessing.json`: full requests, native responses, normalized outputs, usage and latency.
- `mercury-acad-postprocessing-runtime.json`: loaded source and runtime identity.
- `mercury-acad-postprocessing-manual-review.json` and `.md`: all 40 per-output reviews and comparison statistics.
