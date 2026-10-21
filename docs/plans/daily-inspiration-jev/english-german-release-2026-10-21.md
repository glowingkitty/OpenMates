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

## Verification

- 227 focused backend tests passed, including retries, cancellation, exact source
  identity, mixed locales, pixel gating, old-proof rejection and static recovery.
- 29 benchmark-accounting tests passed. Reviewer usage is recorded separately
  from writing attempts; raw responses are not billed twice in the analysis.
- Fourteen fixed real-provider English/German controls matched all labels:
  seven faithful positives accepted, seven negatives withheld. One timeout
  succeeded on its single retry. Automated controls are not native-speaker gold.
- Independent code review found no blocking issues.
- Isolated CI, deployment and deployed refresh results are recorded below when
  completed; these offline/control results alone do not claim live deployment.

## Costs and remaining work

The original pre-Jev/pre-Mercury replay averaged **$0.01927 per attempted refresh**
under its declared extended deadline, including gross search pricing. Those
samples were incomplete. The previous v6 replay averaged **$0.02958 launch /
$0.03485 regular** and was also incomplete; neither establishes a successful-set
price or a production invoice.

The selected fourteen-case Gemini reviewer check captured **$0.05909** at the
uncached introductory tariff, including thinking tokens. One canceled request
has unknown spend. This is a review-only diagnostic, not a complete refresh price
or total experiment-spend upper bound. Deployed refresh measurements follow below.
No cost saving against the original architecture is claimed.

Remaining recommendations, without blocking this scoped release:

- **Medium:** sample accepted English/German cards in normal use and monitor
  missing-source/review failures. Small benchmarks cannot establish universal
  factual accuracy or detect all naturally occurring thumbnail deception.
- **Medium when expanding usage:** improve copy-review yield and role fidelity
  in the other eighteen languages. Their current Jev checks are conservative,
  and a known Turkish causal-role regression remains unresolved.
- **Low:** consider batch processing and bounded reuse of unchanged public-copy
  reviews if actual volume makes costs material. Thumbnail freshness still needs
  separate review. Recheck introductory supplier tariffs before January 2027.

Detailed unsuccessful experiments and their captured costs are retained in
[the diagnostic report](optimization-diagnostics-2026-10-21.md). They are not
deployed alternatives or release qualification evidence.
