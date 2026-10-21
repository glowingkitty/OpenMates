# media.ccc.de published captions

Verified 2026-10-21 against the [official API documentation](https://github.com/voc/voctoweb#public-graphql-api)
and live API. The [site documentation](https://media.ccc.de/about.html) confirms SRT/WebVTT subtitle downloads.

## Scope and contract

`videos.get_transcript` accepts HTTPS `media.ccc.de/v/<slug>` URLs alongside
YouTube watch/youtu.be URLs. Retrieve published captions only, preserving grouped
request IDs, language preferences, timestamps, word/character counts and the
existing output safety pipeline. Missing captions produce a visible error;
neither the page description nor downloaded audio substitutes for a transcript.
No new REST route, authentication, pricing or audio transcription is introduced.
YouTube creator-income tracking applies only to YouTube results.

| Method | Endpoint | Input | Output |
| --- | --- | --- | --- |
| POST | `https://media.ccc.de/graphql` | `lectureBySlug(slug: $slug)`, `$slug: ID!` | `title`, `originalLanguage`, `subtitles { url mimeType language }` |
| GET | Selected subtitle URL on CCC's CDN | Public caption file path | SRT or WebVTT |
| HEAD | `https://media.ccc.de/about.html` | None | Health status; no download/billing |

Example GraphQL variables: `{"slug":"39c3-a-post-american-enshittification-resistant-internet"}`.
The talk exposes `language: eng`, `mimeType: text/vtt` and an HTTPS CDN URL.
Normalize `eng` to `en` and `deu`/`ger` to `de`; match two/three-letter and regional
preferences. Prefer WebVTT over SRT within the first matching requested language.
Defaults remain `en`, `de`, `es`, `fr`; unmatched requests list available languages.

A cue `00:01.250 --> 00:03.500` containing `Hello &amp; welcome` becomes
`{start: 1.25, duration: 2.25, text: "Hello & welcome"}` in the provider wrapper,
then `[00:00:01.250] Hello & welcome` in the skill's existing transcript format.
CCC results additionally identify `provider: media.ccc.de` and UI-only title metadata.

## Authentication, cost and privacy

No API key, Vault secret, account, proxy or provider charge is needed. Existing
Videos skill pricing remains unchanged. No published numerical quota was found;
the wrapper bounds requests and retries instead of assuming unlimited capacity.
The public talk slug and caption path go server-side to CCC and its subtitle CDN
mirror. No OpenMates user identifiers, cookies, chat text or client IP are sent.
The [provider privacy policy](https://media.ccc.de/about.html#privacy) was verified
on 2026-10-21; it describes anonymized logs. OpenMates provider disclosures are updated.

## Limits and failures

- 45-second overall deadline, 15-second HTTP timeout, at most three attempts for
  transport failures, 429, 502, 503 and 504. Exponential backoff begins at 0.5 s;
  numeric Retry-After is capped at 5 s. No retries for absent captions or invalid input.
- Responses are limited to 5 MiB. Only subtitle resources are fetched; thumbnail
  metadata VTT and video/audio resources are never mistaken for captions.
- HTTPS caption downloads allow only `cdn.media.ccc.de`, `static.media.ccc.de`,
  and `mirror.selfnet.de` (CCC's currently observed subtitle mirror), with at
  most three redirects. A mirror change fails visibly and requires allowlist review.
- Not all talks have captions; no automatic translation or speech recognition.
  Missing talks, languages, captions, invalid files and outages return safe errors.
- No new plaintext cross-request cache. Batch concurrency follows the existing
  skill execution path. Larger-scale use should coordinate quotas with c3voc.

## Verification

`python3 scripts/api_tests/test_media_ccc_api.py` checks the user's captioned 39C3
talk (English VTT), BahnMining (German SRT), and the original Hacker-to-Furry talk
(no published captions). Use `--test` or `--list` to select probes.
Deterministic unit tests cover parsing, language selection, URL validation,
redirect restrictions, bounded retries, size limits and deadlines. Real OpenMates
summary verification uses automatic inference routing on dev and isolated CLI state.
