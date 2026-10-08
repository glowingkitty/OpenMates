# Standalone website verification — partial, 2026-10-08

Current implementation candidate: `873323641d4600cc30e3ac1ef129ee0c2265208a`. The Plan remains **implementing**. The receipts below prove the named specs at their own exact tested sources; they do not establish final-source conformance by ancestry. The earlier comparison at `/tmp/a753-current-surface-proof-continuity.json` predates later ActiveChat and newsletter fixes; use the narrower comparison below instead.

| Isolated spec (passed / total) | Tested source | Harness | Run and retained artifact |
| --- | --- | --- | --- |
| `components/marketing-landing.spec.ts` (3/3) | `d69141b5733641213db735d73cc088fd5a3538e2` | `cb9caf5ee16acb57ea4b0b2d9efdf2ee9885ac7c` | [37808829234](https://github.com/glowingkitty/OpenMates/actions/runs/37808829234/artifacts/11563838120) |
| `components/workspace-home-responsive.spec.ts` (5/5) | `d69141b5733641213db735d73cc088fd5a3538e2` | `cb9caf5ee16acb57ea4b0b2d9efdf2ee9885ac7c` | [37808835031](https://github.com/glowingkitty/OpenMates/actions/runs/37808835031/artifacts/11564246570) |
| `components/workflow-detail-tabs.spec.ts` (6/6) | `d69141b5733641213db735d73cc088fd5a3538e2` | `cb9caf5ee16acb57ea4b0b2d9efdf2ee9885ac7c` | [37808840731](https://github.com/glowingkitty/OpenMates/actions/runs/37808840731/artifacts/11564476488) |
| `components/public-newsletter.spec.ts` (7/7) | `26ba264e6e4b7d93ecebac35091f858fca03bf4f` | `6a22845102f5f225e774f138fbe862a52843c808` | [37802385373](https://github.com/glowingkitty/OpenMates/actions/runs/37802385373/artifacts/11561542969) |
| `newsletter-categories.spec.ts` (2/2) | `d69141b5733641213db735d73cc088fd5a3538e2` | `cb9caf5ee16acb57ea4b0b2d9efdf2ee9885ac7c` | [37810916731](https://github.com/glowingkitty/OpenMates/actions/runs/37810916731/artifacts/11565227682) |
| `marketing-landing-route.spec.ts` (4/4) | `4129263a8f2f96e97c86a30b2c9ddc1d102da874` | `a22a2cac89dceb0aa1156c471499c5a8654915fe` | [37815623995](https://github.com/glowingkitty/OpenMates/actions/runs/37815623995/artifacts/11567536115) |
| `openmates-events.spec.ts` (5/5) | `aa3b3bbcf4a3ec55110ae23825d1a02673d57c0e` | `cb9caf5ee16acb57ea4b0b2d9efdf2ee9885ac7c` | [37812693439](https://github.com/glowingkitty/OpenMates/actions/runs/37812693439/artifacts/11565747640) |
| `website-public-routes.spec.ts` (8/8) | `f44de34a1accbe4f6bf984ee196e16b2627ab11e` | `e9dc3dab0283a15d6371af056829d0ea817cdcb4` | [37818606605](https://github.com/glowingkitty/OpenMates/actions/runs/37818606605/artifacts/11568487249) |
| `newsletter-flow.spec.ts` (2/2, no skips/flakes) | `327ac58da7f70236105b92d423de65e54c48e7b3` | `b814e5761587bf036abfc269c76fb2ddc3d714e3` | [37821944969](https://github.com/glowingkitty/OpenMates/actions/runs/37821944969/artifacts/11570051497) |
| `landing-auth-links.spec.ts` (3/3, no skips/flakes) | `873323641d4600cc30e3ac1ef129ee0c2265208a` | `f7fdcd2a04b233e8fab1e568f81a449ca6f84258` | [37823605775](https://github.com/glowingkitty/OpenMates/actions/runs/37823605775/artifacts/11571125543) |

Final-candidate local checks are source-bound to `873323641d4600cc30e3ac1ef129ee0c2265208a`. Before execution, 207 selected website/public-site/lock/backend files matched its Git blobs; afterward, a broader 1,787-file website build-input/backend source check still found zero mismatches. The [build receipt](/tmp/a753-final-bound-local-build.json) records Node 24 `pnpm --filter website check` (0 errors, 0 warnings) and `pnpm --filter website... run build` (public bundle boundary passed; **21 client JS chunks / 61.5 KiB gzip**), with separate logs and SHA-256 fingerprints. The [newsletter receipt](/tmp/a753-final-bound-local-newsletter.json) records the exact four-file pytest command and **16 passed**. These are local checks, distinct from isolated browser/API proof.

## Scoped source continuity

`/tmp/a753-final-surface-continuity.json` records `git diff --quiet` and the exact path scopes for each tested source versus `873323641d4600cc30e3ac1ef129ee0c2265208a`. Equality means the selected tracked files have identical Git blobs and modes. It does not certify unlisted dependencies or replace the Plan verifier's strict single-source check.

| Prior green surface | Scoped comparison to `8733236` | Limit |
| --- | --- | --- |
| Landing component (3/3); existing workflow home (5/5) and detail (6/6) components | Equal: public-site and landing inputs, workflow components, and their focused specs | Component scopes only; app root shell is separate. |
| Public newsletter component (7/7) | Equal: signup/confirmation widgets, newsletter locale helper/payload, focused spec | API route changed; final browser flow remains required. |
| Settings newsletter UI (from categories proof) | Equal: settings component and categories spec | `backend/core/api/app/routes/newsletter.py` changed; the full API categories proof is historical. |
| Public events (5/5) | Equal: event routes/data/generator and event spec | Does not certify unrelated app root shell behavior. |
| Standalone website public routes (8/8) | Equal: entire website and public-site packages, website spec, event generator | App auth and backend newsletter route are outside this scope. |
| Final newsletter browser flow (2/2) | Equal: all tracked frontend and backend files except the auth-links test fixture between source `327ac58…` and `8733236…` | Only `frontend/apps/web_app/tests/landing-auth-links.spec.ts` changed; this does not change newsletter product or its spec. |
| App landing route (4/4) | **Changed:** `frontend/packages/ui/src/components/ActiveChat.svelte` | Full route result remains historical; auth/root behavior needs latest proof. |

The backend newsletter route changed after the earlier categories run, so that run is historical. The later newsletter-flow proof tests the updated subscribe and confirm behavior; the scoped `327ac58…` to `8733236…` comparison preserves its product and spec bytes. No broad unchanged claim is made for auth.

## Accepted-scope conformance before deployment

| Criterion | Passing evidence at exact tested source; continuity to `8733236` where older | Remaining acceptance step |
| --- | --- | --- |
| AC-1 public website and responsive landing | Final-source local website build/check and bundle gate; standalone public routes 8/8 with website/public-site/spec blobs unchanged; landing component 3/3 with selected component blobs unchanged | Deployed laptop/mobile visual smoke |
| AC-2 confirmed newsletter and read-only guest templates | Final-source local newsletter units 16/16; newsletter browser flow 2/2 with all frontend/backend bytes except unrelated auth test unchanged; public newsletter component 7/7 and existing workflow home/detail components 5/5 and 6/6 with selected blobs unchanged | Deployed smoke and recording delivery |
| AC-3 links, events, saved theme and auth return | Final-source auth links 3/3; public events 5/5 with runtime/spec blobs unchanged; prior app landing route 4/4 remains historical because `ActiveChat.svelte` changed afterward, while the final auth run covers its changed root/auth path | Deployed links/theme visual smoke |

All listed product and focused local checks passed at their recorded sources. Scoped byte identity supports carrying the unchanged surfaces forward; it is not a claim that the strict Plan verifier's single-source rule passed.

Remaining before completion: perform the authorized scoped dev deploy and reviewed laptop/mobile smoke, then deliver every retained browser recording link. The earlier newsletter-flow retry at source `9bd4…` was flaky; the later 2/2 run above supersedes it. The Plan verifier requires every green receipt's `subject_commit` to equal the Plan's single implementation `subject_commit`; its partial verification will therefore flag historical receipts as stale despite narrow unchanged-file findings. Do not mark the Plan verified until the remaining publication evidence is recorded.
