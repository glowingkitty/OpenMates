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

Focused checks, isolated CI, the four-source English/German comparison and deployment
results will be recorded here. Earlier v7 reports remain historical evidence, not
proof of this simplified configuration.
