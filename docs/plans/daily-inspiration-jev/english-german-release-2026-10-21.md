# Daily inspirations: English/German release

The accepted scope is practical reliability, focused on English and German. The
user explicitly allowed Gemini where Mercury is insufficient and requested an
end to broader optimization experiments. This release does not claim perfect
multilingual classification or independent verification of every video's facts.

## Implemented workflow

1. Public video and Wikipedia discovery supplies real source metadata. Jev 1.14
   reviews source suitability, conspiracy/pseudoscience and misleading-clickbait
   policy, educational fit and category. Popularity cannot establish accuracy.
2. Videos additionally require Jev approval of actual bounded thumbnail pixels.
   Missing, unavailable, uncertain or deceptive image decisions withhold the video.
3. Mercury 3 LOW writes a title, phrase, introduction and three follow-ups from
   the fixed source. Approved source-bound cards survive later attempts. Only
   unresolved sources are repaired: Mercury once more, then Gemini 3.5 Flash-Lite.
4. Completed cards still require Jev policy and cross-language subject coherence.
   English/German copy then receives a separate Gemini 3.8 Flash review of all six
   fields for language, source fidelity, causal roles, qualifiers and follow-up
   relevance. The reviewer cannot rewrite copy or invent source identities.
5. A valid rejection or uncertain review is final for that draft. Only transport
   or schema failure permits one same-model retry. A failed Jev policy/coherence
   or thumbnail decision cannot be overridden. Other locales retain their
   deployed granular Jev copy checks.
6. Current versioned proof binds approval to exact source evidence and copy.
   Changed/legacy external cards need review again. Public reads invoke no paid
   inference. Localized static recovery remains available in all twenty languages;
   incomplete personalized refreshes preserve the previous set.

Policy/proof version: `daily-editorial-v7`. Public cache namespace: `v16`.
Ordinary account/chat routing and encryption are unchanged.

Generation uses the requested feed language for the copy and localized discovery;
Wikipedia source editions remain attached to their real source. Public defaults
reuse approved pool entries separately for each language, score them by engagement
and age, and select a daily mix. Missing language stock is filled with localized
static cards, never English pool copy relabeled as another language. Existing daily
scheduling remains generation at 06:00 UTC, pool audit at 06:15 and selection at
06:30. Sharing the public pool avoids generating a new twenty-language set for
every visitor; cached public reads and static recovery incur no new inference.

## Writer decision

Keep the existing Mercury retry chain. In the completed frozen-source comparison,
Mercury admitted 34 cards and Gemini-only writing admitted 39 from 168 eligible
slots per arm. Blinded automated review found zero material errors in Mercury's
admitted cards versus five material errors and one uncertain Gemini card. This is
not human/native-speaker gold, and both arms had low yield under the old granular
Jev copy gate. The new release changes the final English/German review, not that
writer comparison. Fourteen final reviewer controls and two live refresh samples
are the bounded completion check; a new broad comparison is not required.

## Verification

- 227 focused backend tests passed, including retries, cancellation, exact source
  identity, mixed locales, pixel gating, old-proof rejection and static recovery.
- 29 benchmark-accounting tests passed. Reviewer usage is recorded separately
  from writing attempts; raw responses are not billed twice in the analysis.
- Fourteen fixed real-provider English/German controls matched all labels:
  seven faithful positives accepted, seven negatives withheld. One timeout
  succeeded on its single retry. Automated controls are not native-speaker gold.
- Independent code review found no blocking issues.
- [Isolated CI run 39595728586](https://github.com/glowingkitty/OpenMates/actions/runs/39595728586)
  passed all 226 selected tests. The exact receipt was retrieved and its evidence
  command completed; this unit run contains no browser recordings. The deployed
  core implementation matched the tested candidate; generated assertion metadata
  was regenerated against the current integration base. A later one-label wiring
  correction passed 36 focused local tests, including the real tracing validator,
  plus Ruff; the deployed refresh check exercises that corrected integration.
- Implementation deployed to **dev** as
  `3e33b8c5d1d57d6bdd6ee5edb688f7ba6edbf6c2`, followed by the tracing correction
  `be96267b0894c144e54aec6d914946067a06251e`. Coordinated reload
  `docker-0d806d4a` finished with all seventeen consumers healthy. Both exact-source
  Vercel project checks succeeded. Twelve runtime source hashes matched the
  corrected manifest before paid calls.
- Corrected deployed English refresh completed in **202.66 seconds** with three
  approved videos, three Wikipedia cards and four static tips: the full ten.
  German completed in **60.94 seconds** with one approved video, three Wikipedia
  cards and four tips. The German generation attempt is short by two videos;
  localized public recovery still supplies ten cards, and incomplete personal
  refreshes preserve the prior set. No account/pool writes were performed by this
  read-only generation benchmark. The two German videos were excluded by the
  existing five-year science age limit (publication in 2017 and 2019), after
  successful retrieval, thumbnail checks and writer fallback. This was an age
  policy shortfall, not a missing writer response.
- Both samples observed Jev 1.14.0, Mercury 3, Gemini 3.5 Flash-Lite and Gemini
  3.8 Flash. The English sample exercised unsupported-fact rejection, bounded
  timeout/retry and source-bound repair; provider failures were never approval.
- Independent read-only review of all ten admitted generated cards against their
  retained source projections found no obvious material language, factual-role or
  follow-up blocker. This is automated inspection, not native-speaker sign-off.

The first deployed refresh caught an unregistered tracing-purpose label: all
26 attempted semantic reviews stopped locally before contacting Gemini. Both
locales retained only static tips, so that diagnostic is excluded from the
working before/after comparison. The fix uses the existing `inspiration` label;
its regression enters the real `ai_provider_span` validator. The model prompt,
thresholds, retry limits and opaque projection did not change.

## Costs and remaining work

The original pre-Jev/pre-Mercury replay averaged **$0.01927 per attempted refresh**
under its declared extended deadline, including gross search pricing. Those
samples were incomplete. The previous v6 replay averaged **$0.02958 launch /
$0.03485 regular** and was also incomplete; neither establishes a successful-set
price or a production invoice.

The selected fourteen-case Gemini reviewer check captured **$0.05909** at the
uncached introductory tariff, including thinking tokens. One canceled request
has unknown spend. This is a review-only diagnostic, not a complete refresh price
or total experiment-spend upper bound.

| Measured generation workload | Cards produced | Recorded response estimate + gross search |
| --- | ---: | ---: |
| Original pre-Jev/Mercury, English | 7 (incomplete) | $0.01891 |
| Selected setup, English | 10 (complete) | $0.05922 + three unpriced cancellations |
| Selected setup, German | 8 (incomplete) | $0.04222 |

The original English/Japanese average above and this English/German workload are
not a matched locale/source comparison; there is no historical German sample.
Google cache counters are missing, so its captured responses use an uncached
upper estimate. Canceled English requests have unknown spend: $0.05922 is not a
bound on all attempted spend. Gross search contributes $0.015 per sampled refresh,
before credits. Native Mercury responses that incurred costs but failed parsing
are included. No cost saving against the original architecture is claimed.

Gemini's stronger semantic review is the main added inference cost. Cached public
reads and static delivery make no new inference calls. Pool revalidation and
infrastructure are outside these two generation samples. See [the full cost
breakdown and pinned ledger](english-german-refresh-costs-2026-10-21.md).

Remaining recommendations, without blocking this scoped release:

- **Medium:** find recent German replacements after the existing age exclusions,
  preferably before paying for copy generation; preserve the age policy. Monitor
  personalized refresh yield, writer fallback frequency and review timeouts, and
  sample accepted English/German cards in normal use. Small benchmarks cannot
  establish universal factual accuracy or detect all naturally occurring thumbnail deception.
- **Medium when expanding usage:** improve copy-review yield and role fidelity
  in the other eighteen languages. Their current Jev checks are conservative,
  and a known Turkish causal-role regression remains unresolved.
- **Low:** consider batch processing and bounded reuse of unchanged public-copy
  reviews if actual volume makes costs material. Thumbnail freshness still needs
  separate review. Recheck introductory supplier tariffs before January 2027.

Detailed unsuccessful experiments and their captured costs are retained in
[the diagnostic report](optimization-diagnostics-2026-10-21.md). They are not
deployed alternatives or release qualification evidence.
