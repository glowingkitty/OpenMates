# Task ordering compatibility

The canonical fixture is `tests/sdk-conformance/fixtures/task-order.json` in the
repository root. `python3 scripts/sync_rust_sdk_fixtures.py --check` verifies this
standalone package copy. The fixture records the exact offline Node binary hash,
Node/ICU/Unicode/CLDR versions, original source commit and each locale's
`Intl.Collator(locale).resolvedOptions()`. It is not a receipt for a current CI
binary or macOS. The original policy is stable `position` subtraction followed
by `title.localeCompare`, with no Task ID tie breaker.

Positions retain JavaScript Number comparison: finite fractional, negative and
large JSON numbers are accepted; missing/null becomes zero; -0 equals zero;
integers beyond 2^53 receive the same f64 rounding as JavaScript. Missing/empty
decoded titles use the original ordinary/projection display fallback. Unknown
row metadata is preserved, and invalid typed fields reject the whole sort before
mutation. Transport pagination, filtering, authentication and CLI JSON/list order
do not change.

The 22 vectors include stable Unicode canonical equivalence, case and accents,
CJK, emoji, large/fractional positions, title fallbacks and invalid input. Locale
coverage includes en-US, de-DE, sv-SE, da-DK, tr-TR, th-TH and ja-JP, plus numeric
and German phonebook extensions. Danish default `caseFirst: upper` and Thai
default `ignorePunctuation: true` come from locale data; neither is overridden.

The SDK accepts an explicit BCP47 locale and never reads environment variables.
The native application resolves LC_ALL, LC_MESSAGES, then LANG, converts POSIX
codesets/underscores, and rejects unsupported POSIX modifiers. Its C/POSIX/unset
fallback is qualified to the Node 24 Linux oracle's en-US behavior. A macOS host
without a locale environment has no proven OS-preference equivalence yet. Invalid
or unavailable locale policy fails visibly instead of using byte ordering.

Pinned implementation: ICU4X collator 2.3.1 and data 2.3.0 (CLDR 48.2.1,
ICU export release-78.1rc), versus oracle Node 24.20.0 / ICU 78.3 / CLDR 48.0.
These vectors qualify compatibility for those inputs, not universal equality
across versions or ill-formed UTF-16 strings.

The six additional packages are icu_collator 2.3.1, icu_collator_data 2.3.0,
icu_locale_fallback 2.3.0 and icu_locale_fallback_data 2.3.0 (Unicode-3.0), plus
utf16_iter 1.0.5 and write16 1.0.0 (Apache-2.0 OR MIT). Existing ICU normalizer,
properties, provider and locale-core versions are reused. Together the six
downloaded crate archives occupy 1,849,429 bytes, unpacked source/data 9,297,255
bytes. These are package sizes, not executable growth: final release/linker and
WASM size measurements remain separate verification work. See the SDK NOTICE
and each upstream package's license. The same coordinated lock update also
patches Tokio 1.54.0 to pinned 1.54.1; it changes no other pre-existing versions.
