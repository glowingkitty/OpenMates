# Standalone website verification — accepted scope complete, 2026-10-08

Published dev commit: `bb9589cf6a41d61b0c64dcd0e5dc8945878373ab`, from candidate `86ad6b54b186bab746f306b076a9a93e50fc54aa` (parent base `43c41363d49715704284e7ca0329dd4cef8d5ebf`). The accepted implementation, focused checks, scoped dev publication, and reviewed visual smoke are complete. The Plan remains **implementing** because the strict Plan verifier compares every historical test receipt to one global source ID; it does not accept scoped byte identity. The receipts below retain each actual tested source.

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
| `landing-auth-links.spec.ts` (3/3, no skips/flakes; integrated) | `450f65efa7b3816472f0a060a536cbbd9acc860e` | `f4279f353df9ff8f7af2eaf8fa117dde69c68f14` | [37830440341](https://github.com/glowingkitty/OpenMates/actions/runs/37830440341/artifacts/11573666989) |
| `landing-guest-workflows.spec.ts` (1/1, no skips/flakes; integrated) | `450f65efa7b3816472f0a060a536cbbd9acc860e` | `f4279f353df9ff8f7af2eaf8fa117dde69c68f14` | [37830416054](https://github.com/glowingkitty/OpenMates/actions/runs/37830416054/artifacts/11574031139) |

The focused local checks are source-bound to `873323641d4600cc30e3ac1ef129ee0c2265208a`; they are historical for the later publication candidate. Before execution, 207 selected website/public-site/lock/backend files matched its Git blobs; afterward, a broader 1,787-file website build-input/backend source check still found zero mismatches. The [build receipt](/tmp/a753-final-bound-local-build.json) records Node 24 `pnpm --filter website check` (0 errors, 0 warnings) and `pnpm --filter website... run build` (public bundle boundary passed; **21 client JS chunks / 61.5 KiB gzip**), with separate logs and SHA-256 fingerprints. The [newsletter receipt](/tmp/a753-final-bound-local-newsletter.json) records the exact four-file pytest command and **16 passed**. These are local checks, distinct from isolated browser/API proof.

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

## Integrated publication continuity

`/tmp/a753-lint-fix-continuity.json` compares **343 selected paths** at integrated tested source `450f65efa7b3816472f0a060a536cbbd9acc860e` with current publication candidate `86ad6b54b186bab746f306b076a9a93e50fc54aa`. Only three source files differ: the event detail page now uses explicit `untrack(() => data.spaUrl)` for its one-time SSR seed/onMount behavior, and the app and website legal pages have scoped trusted-HTML annotations for server Markdown (`html: false`) or serialized repository JSON-LD. Generated `specifications/generated/assertion-index.yml` also differs; the changes preserve event URL behavior and legal content, and the three-file ESLint check passed. The parent base `43c41363d49715704284e7ca0329dd4cef8d5ebf` is publication lineage, not the comparison target. The earlier `/tmp/a753-integrated-publication-continuity.json` documents the preceding 340-path candidate. Neither comparison claims entire-repository identity or rewrites the original CI `subject_commit` values.

## Publication and deployed review

`/tmp/a753-lint-fixed-deploy-result.json` records publication-helper exit 0 for candidate `86ad6b…`; the lint and six-file pytest gate passed. The published commit is `bb9589…`. `/tmp/a753-dev-readiness.json` reports a successful [Vercel dev deployment](https://vercel.com/marcos-projects-e740a395/open-mates-webapp/2YMe9eEumy9NnU2fsx3s7K6qRJSf) at that exact commit. Docker operation `docker-9ebc50d6` restored the API and workers; all 16 services reported healthy. The subsequent dev head `eff4f95…` has the same frontend tree as `bb9589…`; `/tmp/a753-final-deployed-review.json` reports no differences among the candidate and published 343 selected paths.

The explicit sessions visual smoke passed for `bb9589…`. `/tmp/a753-final-deployed-smoke/summary.json` records eight light-mode laptop/mobile pages at `app.dev.openmates.org` (landing and privacy, terms, imprint): HTTP 200, no horizontal overflow, broken images, browser errors, or request failures. `/tmp/a753-final-dark-review/summary.json` adds six reviewed dark-mode hero/device/open-source stills at laptop/mobile widths. All 14 PNGs were reviewed with **no visual defects**. Dark stills used reduced motion; normal mobile scrolling was also reviewed. This is the scoped dev app publication; the separate website Vercel project remains a later external setup using the documented instructions.

## Accepted-scope conformance

| Criterion | Passing evidence at exact tested source and deployed review | Result |
| --- | --- | --- |
| AC-1 public website and responsive landing | Source-bound website build/check and 61.5 KiB client boundary; standalone public routes 8/8, landing component 3/3, deployed laptop/mobile landing and ordinary legal pages reviewed | Satisfied |
| AC-2 confirmed newsletter and read-only guest templates | Source-bound newsletter units 16/16; double-opt-in browser flow 2/2; integrated guest route 1/1; public newsletter component 7/7 and existing workflow home/detail components 5/5 and 6/6 | Satisfied |
| AC-3 links, events, saved theme and auth return | Integrated auth links 3/3; public events 5/5; app landing route 4/4 historical at its exact source; deployed responsive light/dark landing review | Satisfied |

All listed product and focused local checks passed at their recorded sources. Integrated guest/auth runs exercised the assembled source. Earlier public legal file differences were mechanical whitespace fixes; later trusted-HTML annotations left rendered content unchanged, and deployed legal smoke passed. Scoped byte identity does not mean the strict Plan verifier's single-source rule passed.

All 90 retained browser recordings, including failures and retries, have uploaded URLs in `/tmp/a753-final-video-links.md`. Delivery in the parent's final response and live Task closure remain administrative handoff items. The earlier newsletter-flow retry at source `9bd4…` was flaky; the later 2/2 run supersedes it. The strict Plan verifier still flags historical receipt source IDs against published `bb9589…`; those IDs must stay factual. No unrelated suite rerun is required to resolve this bookkeeping limitation.

Task bookkeeping: the parent attempted to close the main implementation Task after deployed review. The CLI rejected delivery with HTTP 400 and retained the operation; no closure acknowledgement is claimed and the pending operation was not resubmitted. Product implementation and scoped acceptance evidence are complete.
