# Teams

> **Status:** Planned
> **Last updated:** 2026-04-16

OpenMates is built for individuals and small teams — not enterprises. Teams lets a group of people share a credit balance, collaborate in shared chats, and manage usage together. No sales calls, no "contact us" pricing, no enterprise tier. A freelancer and their 3 contractors can set up a team in 30 seconds, the same way a 60-person agency can.

---

## Core Concepts

### Team Account

A team is a separate entity with its own:
- **Credit balance** (independent from members' personal balances)
- **Billing details** (business address, VAT ID, invoices)
- **Shared chats** (team-scoped, visible to members based on permissions)
- **Usage tracking** (per-member and per-group breakdowns)

A user's personal account and team memberships are fully separate. Personal chats, credits, and data are never affected by team membership.

### Team Size

- **Minimum:** 1 member (the owner)
- **Maximum:** 100 members

This cap exists by design. OpenMates is not for large corporations — it's for individuals and small-to-mid-size teams. 100 covers freelancers, agencies, startups, small companies, and departments within larger orgs who want to self-organize.

---

## Roles & Permissions

| Role | Manage Members | Billing & Credits | Set Usage Limits | See All Usage | Create Team Chats | Use Team Credits |
|------|---------------|-------------------|------------------|---------------|-------------------|------------------|
| **Owner** | Yes | Yes | Yes | Yes | Yes | Yes |
| **Admin** | Yes | Yes | Yes | Yes | Yes | Yes |
| **Member** | No | No | No | No | Yes | Yes |
| **Viewer** | No | No | No | No | No (read-only) | No |

- **Owner:** Exactly 1 per team. Created the team. Only role that can delete the team or transfer ownership. Can do everything an Admin can.
- **Admin:** Appointed by Owner. Full management access except team deletion and ownership transfer.
- **Member:** Standard participant. Can use team credits in team chats, create team chats, participate in shared chats they have access to.
- **Viewer:** Read-only access to team chats they're added to. Cannot send messages, use credits, or create chats. Useful for stakeholders who need visibility but don't actively participate.

---

## Joining a Team

### Invite Methods

1. **Invite link / code** — Anyone with the link can request to join. Admins approve or reject.
2. **Direct invite by email** — Admin sends invite to a specific openmates.org email. User receives notification and can accept.
3. **Domain restriction** — Team can restrict membership to specific email domains (e.g., only `@theircompany.com`). Combined with invite link for self-service onboarding.

All join requests require admin approval unless the user was directly invited by email.

### Multi-Team Membership

A user can belong to multiple teams. The UI provides a team switcher (in sidebar or account menu) to switch active context. The active team determines which credit balance and shared chats are visible.

---

## Credits & Billing

### Credit Balance

- Each team has its own credit balance, completely separate from members' personal balances.
- **Personal → Team transfers:** Users can transfer credits from their personal account to their team. One-way only.
- **Team → Personal transfers:** Not allowed. Prevents abuse where admins funnel shared credits to personal accounts.
- **Credit purchases for teams:** Bought through the team billing settings by Owner or Admin.

### Usage Limits

Admins can set optional credit usage limits per:
- **Individual user** — e.g., max 500 credits/week for a specific member
- **User group** — e.g., "Design team" gets 2000 credits/month collectively
- **Time period** — daily, weekly, or monthly caps

When a user hits their limit, they see a clear message explaining the cap and when it resets. They can still use their personal credits in personal chats.

### Credit Visibility

Admins can configure what non-admin members see:
- **Total team credit balance** — show or hide per user, per group, or for all non-admins
- **Own usage** — always visible to the user themselves
- **Others' usage** — never visible to non-admins (only admins see per-user breakdowns)

### Invoicing

Team credit purchases generate invoices with:
- Business name and full address
- VAT ID (if provided)
- Line items with credit amounts and pricing
- PDF download from billing settings

Uses the same Stripe infrastructure as personal purchases, but with a separate Stripe Customer per team.

### Usage Dashboard

Available to Owner and Admin in team billing settings:
- Total team spend over time
- Per-user breakdown (filterable)
- Per-group breakdown (filterable)
- Export as CSV

---

## Team Chats

### How They Work

Team chats are group conversations where multiple team members can participate. Key difference from personal chats:

- **@openmates mention required** — The AI assistant only responds when explicitly mentioned with `@openmates` in the message. This allows team members to discuss topics among themselves without triggering AI responses.
- **User identity visible** — Messages show the sender's display name and profile image. No anonymous messages in team chats.
- **Team credits used** — AI responses in team chats consume team credits, not personal credits.

### Chat Visibility

- **Team-public chats** — Visible to all team members (default)
- **Private team chats** — Only visible to explicitly added members (e.g., a project subgroup)
- Viewers can read chats they're added to but cannot send messages

### Moving Chats

Users can move a personal chat to their team:
- The chat becomes a team chat, visible to team members (or a subset if made private)
- Original message history is preserved
- Credit usage switches from personal to team going forward
- This action is irreversible (the chat cannot be moved back to personal)

### Chat Ownership

- The user who creates or moves a chat is the chat creator
- Team admins can manage (archive, delete) any team chat
- Members can only manage chats they created

---

## Member Offboarding

When a member leaves or is removed:
- Their messages in team chats **remain** (attributed to "[Former Member]" or their name at time of departure)
- Their personal account is **unaffected** — personal chats, credits, and data stay with them
- Any unused credit limits are freed up
- They lose access to all team chats immediately
- If they were the only admin besides the owner, no special action needed (owner always retains full access)

---

## Audit Log

Visible to Owner and Admin. Records:
- Member joins, leaves, removals, role changes
- Credit purchases and personal → team transfers
- Usage limit changes
- Chat creation, moves (personal → team), archival, deletion
- Billing detail changes (address, VAT ID)
- Team settings changes

Entries include: timestamp, actor (who did it), action, target (who/what was affected).

---

## Data & Encryption

### Team Encryption Keys

Team chats use team-scoped encryption keys, separate from personal encryption keys. When a member joins, they receive the team key (encrypted with their personal public key). This follows the same key-sharing pattern as the existing E2EE architecture.

### Key Rotation on Member Removal

When a member is removed, the team encryption key must be rotated. New messages use the new key. The removed member retains the ability to read messages sent before their removal (they had the key at that time) — but this is moot since they lose access to the UI.

### Data Isolation

- Team data (chats, usage, billing) is stored in team-scoped collections/tables
- Personal data is never mixed with team data at the storage level
- Deleting a team does not affect members' personal accounts

---

## Team-Scoped Settings

Admins can configure for the whole team:
- **Enabled apps & skills** — restrict which apps are available in team chats (e.g., disable image generation to control costs)
- **Team memories** — shared context that applies to all team chats (e.g., "We are a design agency based in Berlin, our clients are...")
- **Default AI preferences** — default model, language, tone for team chats (members can override per-chat)

---

## Open Questions

### Product & UX

- [ ] **Team switcher UX** — Where does the team switcher live? Sidebar, top bar, account menu? How does it interact with the existing chat list (show personal + team chats mixed, or separate views)?
- [ ] **Notifications** — How are team chat notifications handled? Same as personal? Separate notification preferences per team?
- [ ] **@openmates variants** — Should there be a shorter trigger, like `@om`? What about `@` followed by a specific skill name (e.g., `@openmates-translate`)?
- [ ] **Chat moving confirmation** — What does the UX look like when moving a personal chat to a team? Warning about irreversibility? Choose visibility (public/private)?
- [ ] **Free team tier** — Is creating a team free (with the team just needing credits to use AI)? Or does team creation itself require a minimum credit purchase?
- [ ] **Team discovery** — Can teams be listed publicly (e.g., an open community team)? Or are all teams private by default?
- [ ] **Viewer role use cases** — Is Viewer needed for v1, or can it wait? What's the concrete use case (client access, stakeholder review)?

### Technical

- [ ] **Team key distribution** — How exactly are team encryption keys shared with new members? Does the inviting admin encrypt the team key with the new member's public key? What if the admin is offline when the member accepts?
- [ ] **Key rotation performance** — On member removal, all active team members need the new key. With 100 members, is this a single batch operation or does it happen lazily?
- [ ] **Credit transfer atomicity** — Personal → team transfer must be atomic (debit personal, credit team in one transaction). How does this work with the existing Stripe/credit infrastructure?
- [ ] **Multi-team chat list queries** — If a user is in 5 teams, how does the chat list query work? Separate queries per team? Unified query with team_id filter?
- [ ] **Rate limiting** — Should team chats have different rate limits than personal chats? A 100-member team could generate significantly more requests.
- [ ] **Offline/sync** — How do team chats interact with the existing IndexedDB-based offline sync? Separate stores per team?

### Billing & Legal

- [ ] **VAT handling** — Reverse charge for EU B2B? Which payment processor handles VAT validation (Stripe Tax, manual)?
- [ ] **Invoice customization** — Do teams need PO numbers, cost center references, or other fields beyond business name + VAT ID?
- [ ] **Refund policy** — If a team is deleted, are remaining credits refundable? Transferable back to the owner's personal account?
- [ ] **Data retention on team deletion** — How long is team data kept after deletion? Immediate purge, 30-day grace period, or export-then-delete?
- [ ] **GDPR for team chats** — When a user exercises right-to-erasure, what happens to their messages in team chats? Anonymize vs. delete?

### Scope / Prioritization

- [ ] **v1 feature cut** — Which features are v1 vs. later? Candidates for "later": user groups, audit log, team memories, SSO, domain restriction, viewer role
- [ ] **Migration path** — Will there be existing users who need to convert personal usage to a team? Or is it purely additive?
- [ ] **SSO / SAML** — Not enterprise, but even small teams use Google Workspace or Microsoft 365 SSO. Worth supporting domain-verified SSO for convenience (not as an enterprise upsell)?
- [ ] **API / webhook access** — Should teams get programmatic access to team usage data or team chats? Or is this out of scope entirely?
