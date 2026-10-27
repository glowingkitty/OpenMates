# Daily inspirations: one decision model, one LLM

The user approved Jev 1.14 plus Gemini 3.8 Flash as the sole generation LLM.
This replaces the previous Mercury/Gemini fallback plus separate LLM review setup.

## Workflow

1. Retrieve real localized video/Wikipedia evidence. Jev screens suitability,
   policy, ranking/category and actual bounded video thumbnail pixels.
2. Gemini 3.8 Flash writes the title, phrase, introduction and three follow-ups
   from the fixed source in the requested language. It is the only LLM stage.
3. Deterministic source/schema checks and Jev copy/coherence/relevance checks
   decide admission. There is no second LLM reviewer. A failed provider or
   malformed/missing response may retry the same writer once; editorial rejections
   do not trigger another writing request. Already approved source objects remain.
4. Localized static recovery remains available in all twenty languages. Incomplete
   personalized refreshes preserve the previous set. Public reads make no new
   inference calls; background shared-pool Jev review is a separate activity.

Policy/proof: `daily-editorial-v8`. Public cache namespace: `v17`.
Ordinary account/chat model routing and encryption are unchanged.

## Active-user limits

The scheduled personal job requires tracked request activity less than twenty-four
hours old and at least one recorded inspiration view since successful generation
(subject to the existing view-counter TTL). First-run seeds require recent tracked
activity but no prior view, because those are the user's initial cards. Missing,
stale or unavailable first-run activity skips generation. The current completion
flag prevents a completed first run from repeating for seven days. Tracking can
include zero-credit requests; this is activity tracking, not proof of positive spend.
Signup, login recovery and anonymous defaults do not create new personalized sets.

## Verification and deployment

- All **264 focused checks passed** locally and in [isolated CI run
  39644743177](https://github.com/glowingkitty/OpenMates/actions/runs/39644743177).
  The exact receipt was retrieved and its evidence command completed; this unit
  run has no recording inventory. Scoped Ruff passed.
- Coverage includes same-model provider/schema retry, terminal editorial rejection,
  source-bound object retention, actual image gate failures, all static locales,
  current proof rejection, anonymous no-inference and fourteen activity cases.
- Independent core review found no material blocker.
- Implementation deployed to **dev** as
  `1c60de459e0a4e828f6c886e8e8cf68bc23fa710`. Scoped app/test files matched the
  tested candidate; unrelated local dispatcher adoption files were excluded.
- Coordinated runtime operation `docker-4120c7ff` completed with all seventeen
  consumers running and healthy. Exact-source frontend readiness passed for the
  implementation commit. All thirteen runtime module hashes matched before
  paid calls.
- The bounded English/German comparison planned four source slots. Three passed
  source eligibility; the English video search returned unrelated Aurora
  city/school/institute material and was withheld before writing. Each writer
  made three calls with no retries, fallback or separate LLM review. Gemini
  admitted one card, Mercury zero, under identical Jev gates. All six drafts had
  valid structures and source identities.
- Independent automated inspection of the six drafts against retained source
  evidence found no obvious material copy blocker. Gemini's two rejections came
  from Jev choosing the correct language/grounding answer below the existing
  confidence threshold. Mercury had similar holds and one unsupported-title
  decision despite literal source support. This is a conservative-admission
  limitation, not evidence of a writer-quality winner or native-speaker gold.

## Costs and remaining work

The runtime now pays for one LLM writing stage plus Jev decisions, rather than
writing followed by a separate LLM review. A provider/schema retry can still
incur a second call to the same writer. No cross-model fallback is configured.
The [small native comparison](single-llm-comparison-2026-10-21.md) records actual
supplier usage and its accounting limits. It does not establish the cost of a
complete personal refresh or savings against the pre-Jev/Mercury architecture;
the [original-architecture baseline](pre-jev-baseline-2026-10-21.md) remains a
historical replay, not a production invoice.

The approved dev simplification and activity guard are delivered. Keep the
existing source, safety, image and copy thresholds. The next optional improvement
is a small labelled English/German Jev calibration check, particularly false
language/grounding rejections; priority is medium because localized static
recovery and the prior personal set cover incomplete results. Recent relevant
German video discovery is also a medium-priority yield improvement. Neither
requires another LLM stage. Batch processing, broader twenty-language quality
qualification and first-run concurrency/cooldown changes remain outside this
follow-up. No production-server deployment was performed.
