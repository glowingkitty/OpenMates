# Multilingual inspiration and thumbnail qualification

The approved follow-up replaces lexical media overlap with Jev semantic checks,
requires source-specific follow-ups, localizes static recovery in all twenty feed
languages, screens actual video thumbnail pixels, and compares the requested
Mercury/retry/Gemini chain against Gemini-only before the deployment decision.

## Implementation and verification

Dev candidate: `1c753c461f9b97e1bc1e4c61c1d06b431e19bae1`.
The setup-gated runtime operation `docker-2074e2a0` applied additive review fields
before recreating the API and seventeen affected backend consumers; all were healthy.
The candidate frontend deployment completed successfully.

- 134 focused backend cases passed across admission, recovery, generation, locale
  completeness, persisted proof and image transport; 19 frontend unit cases passed.
- [Isolated native decision boundary](https://github.com/glowingkitty/OpenMates/actions/runs/39471945379) passed.
- [Component navigation](https://github.com/glowingkitty/OpenMates/actions/runs/39471951724) passed both cases, including Japanese card/source-edition identity.
- [Public feed](https://github.com/glowingkitty/OpenMates/actions/runs/39474468256) passed German and Japanese navigation/reload and withheld-inventory recovery; all twenty endpoint locales returned ten correctly labeled cards.
- CI source: `0bc10e895f172067491e06ecf6128d9ec697d4fa`; harness: `d2733343be7dbfa5cfcd2d8849f8742956f8b6aa`. Its task application files match the published candidate; later harness/report changes do not alter application behavior.

The shared YAML catalog now supplies all fifteen backend static cards across the
21 UI registry locales (including Hebrew), with a backend-only compiled JSON
artifact. The feed's twenty supported languages no longer borrow relabeled
English pool copy. Static Wikipedia cards retain their verified English article
identities and declare the source edition separately from translated card text.

Jev separately reviews policy, factual support, subject coherence, every follow-up's
explicit source concepts and the requested copy language. Japanese and other
unspaced scripts have no lexical overlap gate. Public video defaults carry a
versioned content hash bound to the reviewed copy, language, metadata and thumbnail
identity; anonymous page loads make no paid model calls. Semantic uncertainty
withholds publication without deleting historical pool content.

Actual bounded JPEG pixels go to pinned Jev 1.14 through direct TypeSafe. Missing,
failed or uncertain visual review withholds the video; no text-only fallback can
approve it. Expressive faces/arrows/legible titles alone do not imply deception.
Image support is [experimental](https://docs.typesafe.ai/images); this reviews a
thumbnail snapshot and source metadata, not watched video content or later edits.

## Predeclared comparison

Both writer arms use the same frozen real public source passages and thumbnail
snapshots: five new topic/source pairs per locale, video and Wikipedia, twenty
locales, targeting 200 cards per arm (400 total). Production three-card and two-card
batches exercise the actual assembly, bounded recovery and final Jev admission paths.
Initial source eligibility/ranking and thumbnail approval are obtained live once
and held fixed across arms. Final draft policy, grounding, coherence, follow-ups
and language are reviewed live for every attempt; final video admission can also
re-review the same frozen JPEG pixels. This isolates writing from source-review variation
and is not a benchmark of complete production discovery or candidate ranking.
The Mercury arm is Mercury 3 LOW, one Mercury retry, then Gemini 3.5 Flash-Lite;
the control allows up to three Gemini 3.5 Flash-Lite attempts. Account/chat defaults
are unchanged. Random topic ordering is seeded identically across paired arms.

Retrieval/source eligibility is evaluated before selecting snapshots and retained
separately from writer cost. Wikipedia fallback queries stay on the target edition;
video retrieval locale is recorded without claiming verified spoken language.
Thirty-four holdout admission controls include Japanese semantic paraphrase and
mismatch, a German bridge/wind follow-up drift, policy/grounding/injection cases,
and five image controls. Matched astronomy and clinical-image pairs have identical
neutral metadata; only pixels distinguish educational titles from conspiracy or
miracle-cure claims. The ordinary image is an actual public YouTube thumbnail.

The proposed decision gates remain: no known admitted material unsupported claim,
policy violation or invented source; at least 95% acceptable first drafts and 99%
acceptable completed chains. Source shortages and outages remain separate from
writer failures. Finite format diagnostics do not substitute whitespace counts
for Japanese/Chinese/Thai segmentation. All-field language assessments and an
independent arm-blinded content review are automated, not native-speaker approval.

Native requests, observed model identities, every draft and Jev decision, actual
usage, hashes and latencies are retained in the persistent test-results mount.
Resuming archives incomplete receipts instead of overwriting billed attempts.
Supplier prices are estimates from observed usage and the repository tariff;
missing telemetry is flagged rather than represented as an exact bill.

## Live controls and discovery

The holdout admission controls scored **33/34**, including **5/5 visual controls**.
The image pairs correctly allowed the educational versions and rejected the
flat-earth/NASA-deception and miracle-cancer-cure versions with identical neutral
metadata. This establishes that actual pixels influenced admission, rather than
only titles or descriptions.

The sole incorrect control was a valid Japanese paraphrase conservatively withheld:
semantic coherence was `coherent` at confidence 0.97 and follow-ups `relevant` at
0.91, while grounding confidence was only 0.31. The Japanese lexical-overlap bug is
fixed; this remains a distinct grounding false negative. Thresholds were unchanged.
No unsafe holdout was admitted.

The first end-to-end pilot exposed source-review variation: a previously approved
video received low policy confidence on re-review, so one writer was never called.
The paired comparison therefore freezes the initial live source approval, rather
than counting that variation as a writer failure. A subsequent two-slot pilot gave
Mercury-chain 1/2 final admissions and Gemini 2/2; these pilots are exploratory and
excluded from the qualification sample.

Live Brave requests exposed unsupported language codes (`zh`, `pt`, `id`, `no`)
and countries (`vn`, `th`, `cz`). The implementation maps language codes to Brave's
supported values and uses `all` for unsupported countries, retaining the language
filter. Fourteen focused enum regressions cover these cases and optional locales.

The initial source corpus obtained **183/200** requested source contexts. Fifteen
video shortages are filled using exact same-topic, already approved public
metadata and verified JPEG snapshots from another locale; no writer outputs were
consulted when selecting donors. Two Wikipedia shortages use authoritative
Wikidata sitelinks plus matching real Japanese/Chinese page summaries and fresh
native Jev source gates (`ja:受粉`, `zh:传粉`, both Q134624). These seventeen
backup slots are explicit in provenance. Video spoken language remains unverified.

The initial five-second writer run was stopped after 63 paired batches per arm:
153 slots per arm, Mercury-chain 32 first-draft / 126 final admissions and Gemini
107 first-draft / 132 final admissions. These are exploratory results, not the final
provider comparison. Raw errors revealed that the shared preprocessing adapter
canceled many Mercury requests after five seconds despite the writer's outer
thirty-second allowance. Canceled requests often have no billable usage receipt;
known supplier estimates can materially undercount that exploratory spend.

The correction adds an explicit, finite single-attempt allowance of at most thirty
seconds, usable only when facade retries are disabled. It bounds provider setup and
the request; ordinary preprocessing retains its existing five-second request and
twelve-second total limits. The requested Mercury/Mercury/Gemini chain remains at
most three writing attempts. This changes a demonstrated timeout defect rather than
loosening any editorial decision.

The final controlled comparison uses all **200 source contexts (147 distinct IDs:
47 videos and 100 Wikipedia articles)** and targets **400 fresh copy slots**. It
reuses source passages and JPEGs but no writing results from the five-second run.
Exploratory runs, earlier partial batches and their costs remain separate from the
final comparison. An initial blinded review of 153 exploratory admitted cards found
six material source/meaning errors after adjudication; those observations are not
counted as final-copy review results.

## Paired result and deployment decision

Final paired metrics and blinded adjudication are pending. No setup is currently
claimed to meet the proposed 95 percent first-draft / 99 percent final targets.

