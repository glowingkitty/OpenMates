# Chat message timeline verification

Specification: `feature.chat-message-timeline@1`, approved fingerprint
`3128cb74c78927919831b54aeb6fa86f22c4319f1e3a5849eb7fc64c9c1031a7`.

| Required check | Result | Evidence |
| --- | --- | --- |
| Bounded catalogue discovery, access guards, identity pairing and text previews | Passed | 16 Python catalogue cases, 22 Directus operation cases and 12 frontend unit cases |
| Compact desktop/phone previews, keyboard navigation, touch cancellation and stable selection | Passed | Nine isolated component cases, [run 39954348153](https://github.com/glowingkitty/OpenMates/actions/runs/39954348153), source `81ddb6c430b9537b8f9985832175796625afbf21`; desktop and phone captures reviewed |
| Unloaded compressed history, failure preservation and return to latest | Passed | Real encrypted 10,000-exchange browser flow, [run 39959606508](https://github.com/glowingkitty/OpenMates/actions/runs/39959606508), source `39588296085b47949f5a8b5dd1377825c7bd38d8` |
| Private yellow bookmarks, encrypted reload and failed-save retry | Passed | Same browser flow plus component and service cases; 51 session, 33 focused login and eight pairing cases verify profile hydration and access boundaries |
| Deployed laptop and phone review | Layout reviewed; network smoke requires scope decision | Feature commit `1ea7a958108cbe2931a4e2415971d273bb0b600b`; matching frontend ready, coordinated runtime operation `docker-d93d1592` completed with all services healthy |

The compact preview contains one truncated question line and up to three muted
response lines. The rail is at the active chat's far-left edge. Active bookmark
icons and their exchange marks are yellow; the reviewed dense-history fixture
keeps a bookmarked exchange visible outside the ordinary overview sample.

Bookmark reload required carrying the existing opaque account settings through
verified session, login and pairing profile hydration. Verification challenges
and anti-enumeration responses continue to omit the ciphertext. No settings
decryption or message plaintext was added to the backend.

Deployed screenshots are retained under
`test-results/visual-smoke/b026-timeline-20261023/`. The timeline and composer
render correctly at both widths. The full-page smoke reports an existing
signed-out request to `/v1/projects/focus/current` returning 401 in the public
example chat. Approval is pending on including that unrelated guard repair or
accepting the warning outside this feature's scope.

The broader local authentication endpoint suite also reported eight unrelated
environment/fixture failures: missing `cbor2` and a stale session-refresh mock.
The relevant focused authentication checks listed above pass; those unrelated
tests and product behavior were not changed.
