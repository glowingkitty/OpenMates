# Chat review checklist and evidence record

Review every applicable item; record why an item is inapplicable. An absence of
obvious errors in a screenshot does not prove an interaction works.

| Area | What to actually inspect or exercise |
|---|---|
| Real conversation | Approved natural opening, CLI provenance and read/react turns; plausible context, useful outcome, no artificial instructions or fabricated output. |
| Routing | Appropriate mate/category and language; requested model actually used; deployed focus/skills activate naturally. |
| Time and facts | Resolve relative dates against generation time and user context; compare like-for-like flight itineraries/prices and appointment availability; note when time-sensitive examples need refreshing. |
| Evidence | Open cited sources; substantiate important research claims with short accurate attributed quotations and direct links. In deep research, follow parent claims back through sub-chat evidence; distinguish inference and disagreement. |
| Transcript | Read the entire chat, not just its first viewport: formatting, inline code/dollar signs, labels, source quotes, translations, overflow, clipping, raw JSON/TOON and stale loading states. |
| Embeds | Inspect each preview and meaningful fullscreen: images/PDF thumbnails load, failed images do not leave blank cards, maps and pins match results, generated artifacts match the request. Close/reopen and follow relevant destination links. |
| Actions | Result links lead to the result rather than settings. Suggested actions and follow-up suggestions work. Prefill visibly focuses/activates the composer and preserves editable text; sending may require guest sign-in but must follow the intended flow. |
| Focus | Finished/shared/example chats have no pending countdown. Check activation, cancellation when actually pending, historical state and banner/composer overlap. |
| Privacy/memories | Fictional prepared data only. Verify supported email/phone detection and replacement; do not claim unsupported address/name protection. Verify actual memory request/consent and relevant selective use; do not imply access to prior emails. |
| Generated app | Use its controls, mobile layout, persistence across reload and any promised functionality. |
| Guest speech | Click each required assistant speak control, observe playback time advancing and listen to confirm intelligible matching content; test stop/resume/replay. Verify immutable public audio loads logged out without private URLs or auth dependency. A manifest or HTTP 200 alone is insufficient. |
| Both viewports | Repeat meaningful interactions on phone/laptop; examine contrast/typography concerns as unclear intentional design, not automatic permission to restyle. Record console/network failures, reload behavior and defects. |

Known video-preview expectations when that surface is assigned: full thumbnail,
white play overlay, overlaid info bar, AI Generate skill icon and human-readable
`via <model>` label. Generated media examples are excluded from this landing
campaign but still need appropriate catalog review.

## Record format

Store a record per example with the campaign evidence (never credentials or
share encryption keys). `files` must include the example TypeScript source and
i18n YAML, plus relevant speech/artifact manifests when present. SHA-256 is
computed from actual file bytes. `deployed_commit` is the full tested commit;
`--expected-commit` is supplied independently from deployment evidence.

```json
{
  "slug": "<slug>",
  "source_chat_id": "<real-chat-id>",
  "deployed_commit": "<full-tested-sha>",
  "reviewed_at": "<ISO-8601-time-with-timezone>",
  "files": {"frontend/packages/ui/src/demo_chats/data/example_chats/<slug>.ts": "<sha256>", "frontend/packages/ui/src/i18n/sources/example_chats/<name>.yml": "<sha256>"},
  "checks": {
    "cli_content": {"status": "passed", "evidence": "<turn IDs and review artifact>"},
    "phone": {"status": "passed", "evidence": "<URL, run ID and interaction review artifact>"},
    "laptop": {"status": "passed", "evidence": "<URL, run ID and interaction review artifact>"},
    "guest_speech": {"status": "passed", "evidence": "<playback observation and artifact>"}
  },
  "verdict": "keep",
  "open_defects": []
}
```

Use `pending`/`failed` and a regenerate/reject verdict for incomplete reviews;
validation should fail until required evidence is present. During a speech pilot
hold, content/browser work can pass independently but admission stays pending.
Within each viewport artifact include this checklist's applicable findings and
inapplicability reasons. The validator intentionally does not judge prose,
listen to audio or certify source truth; those remain review obligations.
