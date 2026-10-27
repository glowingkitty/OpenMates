# Calendar event embed verification

Plan: `docs/plans/calendar-event-embeds/plan.yml`

Specification: `feature.calendar-event-embeds@1`

Status: **pass**, 2026-10-25, within the user-approved Rust deferral.

Product deployed to dev: `252a9a5799a5e453251bb87fbc40a7fd9cfeaf3e`.
The frontend deployment succeeded; coordinated restart `docker-0f648a4a`
completed with all affected services healthy and the public API returning 200.

| Assertion | Result | Evidence |
| --- | --- | --- |
| `calendar-event.content.validated` | pass | Backend validation/lifecycle suites; shared valid/invalid export vectors; 26 TypeScript and 13 Python checks. |
| `calendar-event.assistant.relevant-research` | pass | A normal real dev FOSDEM research request automatically used web search and emitted a saved calendar event with the exact official source URL. Automatic model routing was retained. |
| `calendar-event.streaming.saved-lifecycle` | pass | Backend chunk/finalization and encrypted lifecycle checks; saved-chat browser reload plus CLI retrieval in integration CI. |
| `calendar-event.preview.shared-week-layout` | pass | Shared weekly results renderer; compact/large and phone/laptop component checks; deployed screenshot review. |
| `calendar-event.preview.context-highlight` | pass | Primary/context distinction, reduced opacity, overlap lanes and initial primary week checked in component and saved-chat cases. |
| `calendar-event.fullscreen.details` | pass | Shared fullscreen, optional description/source/location, keyboard expansion and minimal-data cases. Fullscreen screenshot reviewed. |
| `calendar-event.export.primary-only` | pass | Browser preview/fullscreen, actual CLI chat download and npm SDK produce the same stable UID and one VEVENT. Shared Python vectors and both helpers on the real saved event also pass. |
| `calendar-event.privacy.explicit-local-export` | pass | Export requires an explicit action; no context events, attendees or alarms are exported. Saved-chat and real research checks found no calendar mutation. |
| `calendar-event.surfaces.verification-order` | pass with waiver | Current CLI/SDK and real inference evidence accompany web verification. Native Rust SDK/export integration is deferred by the user's explicit “Proceed; defer Rust integration” approval. Apple is outside this stage. |

Successful isolated CI runs:

- Backend validation/streaming: [40189432200](https://github.com/glowingkitty/OpenMates/actions/runs/40189432200), [40190398147](https://github.com/glowingkitty/OpenMates/actions/runs/40190398147).
- Calendar components: [40200084630](https://github.com/glowingkitty/OpenMates/actions/runs/40200084630), source `c02c510afe42c7a3d22f6472c6225fbbba8caf95`.
- Saved browser chat, CLI and SDK export: [40205797803](https://github.com/glowingkitty/OpenMates/actions/runs/40205797803), source `b22ceeef6d7e08875651d1d6b95bbb9f091f6118`; complete coverage, no retries/skips, cleanup verified.
- Existing event-reference hydration: [40199481931](https://github.com/glowingkitty/OpenMates/actions/runs/40199481931).
- Existing results-calendar flight behavior: [40196187212](https://github.com/glowingkitty/OpenMates/actions/runs/40196187212).

Calendar UI source is unchanged between its component run and final integration
run. Subsequent changes fixed CLI encrypted-embed collection/JSON output and the
integration test's initial pairing setup. Deployment integrated upstream metadata
through the session helper. Local Svelte compile, targeted lint/type checks,
backend content/mock regressions and whitespace checks passed.

Deployed screenshot review covered light all-day and dark overlapping events on
laptop and phone. The split, primary/context distinction and three controls stay
in bounds. Defects: none. Accepted differences: none. Session `d194` records the
review against the deployed product commit.

Selected successful browser and actual terminal recordings were uploaded through
the standard evidence transport. The real research chat and its isolated account
state remain private; no credentials or account identifiers are committed here.
Cloud calendar saving remains outside scope. No unresolved decisions remain for
this stage; shared fixtures support the deferred Rust implementation.
