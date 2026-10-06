# Apple canonical embed storage rollout

## Writer contract

The main app and Watch retain one encrypted attempt across retries. They save
the embed head before sending any key wrappers, and retire the attempt only
after both matching receipts succeed. Receipt waiters are registered before
sending. Disconnects, timeouts, partial saves and capability rejections preserve
the original ciphertext, wrappers and request identities.

For a verified canonical server profile, the head receipt must contain the exact
request ID and embed ID, `canonical_source = head`, and the lowercase SHA-256
digest of the exact encrypted-content UTF-8 string. The wrapper receipt must
contain the exact request ID, `created_count == requested_count == keys.count`,
and `failed_count == 0`. Missing or malformed fields cannot complete a save.
Account, Team, generation, deletion and owner-only PII safeguards still apply.

## Installed-client policy

1. Development backend commits `1e7b84c33ea33734ec53c85deda27b90aad3124d`
   and `9f42f3f23c5550c1166d0fdab792c3b113c0c82d` are active, as recorded in
   the canonical Apple handoff. The next Apple build pairs strict receipts and
   `canonical_embed_receipts_v1` with the exact development server profile,
   including every authenticated reconnect, on the main app and Watch.
2. Production and unverified self-hosted profiles retain the legacy policy.
   A matching domain, protocol epoch or incoming capability event cannot enable
   strict receipts; the complete captured server profile must match.
3. The handoff clears the legacy-client compatibility hold for this development
   rollout because the user is its only Apple tester. Existing development
   installs must update; the strict endpoint must not weaken its key guard for
   older writers. Production cutover remains a separate backend-owned decision.
   `client_capability_required` is an update-required result, never save success,
   and retained pending work must remain available after updating.
4. Do not advertise `typed_recovery_outputs_v2`. Typed recovery, archive/message
   readers and bounded artifact-version reconstruction require separate native
   compatibility evidence before real-data pruning.

## Verification boundary

Focused synthetic native tests exercise head-before-key ordering, exact digest
and count validation, unrelated receipt IDs, rejection, immutable reconnect
retry and duplicate delivery. They also preserve scope, deletion and owner PII
coverage. These tests require no inference or active storage API. iOS, macOS and
Watch build receipts and TestFlight availability are reported separately from
backend compatibility.

The development activation decision does not establish native typed-reader,
archive or pruning compatibility. Synthetic writer checks prove client behavior;
inspection of canonical server rows after a real synthetic socket exchange is a
separate integration receipt. Production activation and real-data pruning remain
gated on their required compatibility evidence.
