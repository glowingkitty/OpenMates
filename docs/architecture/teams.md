# Teams

Last updated: 2026-10-06. The permanent product contract is [the Teams Specification](../../specifications/features/teams/specification.yml); this page describes the implementation and its boundaries.

Teams management lives in Settings. Creation checks the normalized lowercase name with our own backend, then opens the profile-image step. Names need not be unique. The video placeholder is hidden pending a real introduction video. The settings quick action enables or disables Team context and opens an animated selector with the five most recently used joined Teams, Show more, and New team. Chats, Projects, Tasks, and Workflows show the selected Team avatar beside their workspace icon.

## Encryption and name policy

Each Team has a client-generated Team key. Its name, description, avatar metadata and optional member display-name/avatar snapshots are encrypted with that key. Each active member has a Team-key wrapper encrypted with their own account master key. Peer avatar requests require both requester and target to be active in the same Team and use private, non-cacheable responses.

Name approval transiently checks the submitted lowercase name against the existing DomainSecurityService blocked names/domains. The backend issues a short-lived, user-bound, single-use receipt required by creation or rename. It does not retain the submitted name or send it to JEV. Supported clients encrypt the approved name before persistence. The receipt intentionally does not prove that a modified client encrypted the same submitted name.

Profile uploads reuse Personal center cropping, 340-pixel JPEG resizing, upload preparation, Sightengine moderation and account-safety consequences. Rejected uploads show the same escalation and final warning behavior. Server-processed Team avatars and billing documents use a Team-owned Vault key, so removing an uploader or payer’s Personal account does not invalidate assets that remain owned by the Team.

## Invitations and member management

Only owners and admins invite members or change roles. Every new member must satisfy the current allowed-domain policy using an email verified for their account. The optional strong-auth policy requires a passkey or two-factor authentication. Direct targeted invitations activate on the intended recipient's acceptance; share links require approval by default. Pending link requests recheck current policy before activation. Unrestricted new links have a short expiry and the UI explains the risk when domain restriction and approval are both disabled.

All invitations contain a Team-key envelope encrypted using HKDF-SHA256 and AES-256-GCM with a client-generated 32-byte fragment secret. The secret stays in the URL fragment and tab-local session storage during login; it never reaches REST, logs, server storage or automatic invitation email. The inviter shares the complete link through their email app or copy-link controls. The UI says the invitation is ready to share, rather than claiming email delivery. After acceptance the recipient wraps the Team key with their own master key; pending approval does not cache an active Team key. Acceptance or decline removes the tab secret; logout purges remaining invitation secrets.

All active roles can read member profiles; only managers can mutate roles or remove members. Successful role changes and removals queue an email to the affected account without exposing the private Team name or content. Removal revokes server access and Team-key wrappers. Automatic Team-key rotation and cryptographic erasure of previously downloaded content remain outside V1.

## Billing contexts

Personal and Team balances, Stripe customers, payment methods, buyer addresses, orders, invoices and recurring billing are separate. Owners/admins manage Team billing through cards, bank transfers, low-balance auto top-up and monthly auto top-up. Personal billing endpoints reject Team orders. CLI and SDK bank-transfer purchases can supply an optional buyer address, and the address can be saved or cleared per context.

Buyer addresses are optional for ordinary qualifying small invoices. Team purchase fields are expanded initially; Personal purchase fields start under Add billing address. Saved addresses and order snapshots are Vault encrypted, independently of client-only Team content keys. Invoice tasks use the order snapshot, never another workspace's address. Team bank-transfer settlement generates the same invoice documents as card purchases. Normal German small-invoice treatment follows [section 33 UStDV](https://www.gesetze-im-internet.de/ustdv_1980/__33.html), including its statutory exceptions.

Credit settlement uses idempotent events. Invoice dispatch records a retryable request and clears the temporary encrypted email key only after the invoice record exists. Repeated completed bank-transfer webhooks reconcile missing invoices without granting credits again. Deletion, payer removal or demotion below admin stops that payer's recurring Team billing before changing access. Durable subscription context maps late paid invoices to their original Team after cancellation or replacement.

## Browser caching and offline limits

One account-scoped IndexedDB stores encrypted Personal and Team records; records retain explicit workspace identity. Switching context replaces visible workspace lists and fences stale asynchronous results. Decrypted image/audio caches revoke blob URLs on context changes and logout. Logout clears account data and purges app-owned plaintext OPFS download staging; an already offered browser save retains its handoff lease until release.

The default offline target is 100 MiB across the browser origin, reduced when available quota is constrained. It is best effort: keys, drafts, unsent changes, pending journal entries and unconfirmed records are protected. Only server-confirmed message pages eligible for safe refetch are trimmed. Candidate selection scans at most 4,096 pages and evicts at most 32 per pass, so oldest-first selection is approximate for very large caches. Protected data can leave total usage above the target. Large files remain on demand.

A quota failure trims safe content and retries once. A failed retry reports a save error and does not acknowledge an offline write before its IndexedDB transaction commits. Browsers can still evict an entire origin, especially under device storage pressure; this does not promise permanent retention or a reliable cold-start offline shell. See [WebKit storage policy](https://webkit.org/blog/14403/updates-to-storage-policy/).
