# OpenMates Creators Program

## Overview

The OpenMates Creators Program ensures that content creators (website owners and video creators) are compensated when their content is processed by OpenMates skills. This program includes both automatic revenue sharing from skill usage and optional user tips.

The program is designed with privacy as a core principle - we track content usage anonymously without storing user information, ensuring both creators and users benefit from a privacy-first approach.

## Implementation Status

### ✅ Currently Implemented

- **Credit Reservation**: Credits are automatically reserved for creators when their content is processed by OpenMates skills
- **Privacy-First Tracking**: Anonymous tracking of content usage with hashed identifiers
- **Revenue Split**: Automatic revenue sharing from Web Read and Videos Get Transcript skills

### 🚧 Coming Soon

- **User Tips**: Direct tipping functionality for users to support creators (planned)
- **Creator Account Signup**: Creator registration and ownership verification (planned)
- **Income Claiming**: Process for creators to claim their reserved credits (planned)
- **Creator Dashboard**: Analytics and statistics for creators (planned)
- **Cash Payouts**: Ability to cash out credits (pending legal review)

**Note**: While credit reservation is fully implemented and working, the creator account system and claiming process are still in development. Reserved credits will be available for claiming once the creator account system is launched.

## How It Works

### Revenue Sharing from Skill Usage

When users make requests to skills that process creator content, a portion of the credits charged to the user is automatically reserved for the creator. This happens automatically in the background - no action is required from creators or users.

#### Supported Skills

1. **Web Read** - When users read website content
   - Total cost: 20 credits per request
   - Creator receives: 10 credits (50%)
   - OpenMates receives: 10 credits (50% - covers operational costs)
2. **Videos Get Transcript** - When users get transcripts from YouTube videos
   - Total cost: 20 credits per request
   - Creator receives: 9 credits (45%)
   - YouTube receives: 1 credit (5% - claimable by YouTube to cover their server costs)
   - OpenMates receives: 10 credits (50% - covers operational costs)

#### Revenue Split Details

The revenue split ensures:

- **Creators receive meaningful compensation** for their content being used
- **Platform partners** (like YouTube) can claim credits to cover their server costs
- **OpenMates covers operational costs** (API fees, infrastructure, development)
- **Fair distribution** that benefits creators, platform partners, and the platform

### User Tips

**Status**: 🚧 Planned - Coming Soon

Users will be able to directly support creators by tipping them with credits:

- **100% of tipped credits will go to the creator** (no platform fee)
- **Tip range**: 50 to 20,000 credits (planned)
- **Available from video embeds**: Users will be able to tip creators directly from video embeds via the "Tip Creator" button or right-click context menu
- **Tips will be reserved** for creators and can be claimed when they sign up for a creator account

**Note**: The tipping functionality is planned but not yet implemented.

## Privacy-First Design

The Creators Program is designed with privacy as a core principle:

### Anonymized Tracking

- **Privacy-first**: All identifiers are anonymized before storage
- **No user tracking**: We don't store which users processed which content - we only track that content was processed
- **Secure storage**: Credit amounts and identifiers are securely stored

### What Creators Can See

Creators can view:

- Total credits reserved and claimed
- Number of content items processed
- Usage statistics

Creators cannot see:

- Individual user information
- Who processed their content
- When specific users accessed their content

## For Creators

### Current Status

**Credit Reservation is Active**: Your content is automatically tracked and credits are reserved when users process it with OpenMates skills. This is happening right now - no action required from you.

**Creator Account System Coming Soon**: The ability to sign up, verify ownership, and claim your reserved credits is currently in development. Your reserved credits are safely stored and will be available for claiming once the creator account system launches.

### How It Will Work (Once Launched)

1. **Automatic Enrollment**: Your content is automatically tracked when users process it with OpenMates skills. No signup required initially - credits are already being reserved for you.

2. **Sign Up for a Creator Account**: To claim your reserved credits, you'll need to:
   - Create an OpenMates account
   - Verify ownership of your content (YouTube channel or website)
   - Link your account to your content

3. **Claim Your Income**: Once verified, all reserved credits will be automatically transferred to your account.

### Content Ownership Verification (Planned)

To claim your income, you will need to verify ownership of your content:

- **YouTube Channels**: Verify via YouTube API (automatic verification)
- **Websites**: Verify via meta tag or DNS record

### Income Claiming Process (Planned)

1. **Reserved Credits**: Credits are automatically reserved when your content is processed (✅ This is already happening)
2. **6-Month Window**: Reserved credits will remain available for 6 months after processing
3. **Automatic Transfer**: When you sign up and verify ownership, all reserved credits will be immediately transferred to your account
4. **Expiration**: Unclaimed credits after 6 months will be transferred to the Youth & Education Fund

### Using Your Credits (Planned)

Once credits are in your account, you will be able to:

- Use them to access OpenMates skills and features
- Build applications using OpenMates APIs
- Support other creators by tipping them

**Note**: Cash payouts are not planned at this time (pending legal review). Credits will be usable on the OpenMates platform.

## For Developers

### Implementation Files

Key files for the Creators Program implementation:

- **Revenue Service**: [`backend/core/api/app/services/creators/revenue_service.py`](../backend/core/api/app/services/creators/revenue_service.py)
- **Web Read Skill**: [`backend/apps/web/skills/read_skill.py`](../backend/apps/web/skills/read_skill.py)
- **Videos Get Transcript Skill**: [`backend/apps/videos/skills/transcript_skill.py`](../backend/apps/videos/skills/transcript_skill.py)
- **URL Normalization**: [`backend/shared/python_utils/url_normalizer.py`](../backend/shared/python_utils/url_normalizer.py)
- **Content Hashing**: [`backend/shared/python_utils/content_hasher.py`](../backend/shared/python_utils/content_hasher.py)
- **API Endpoints**: [`backend/core/api/app/routes/creators.py`](../backend/core/api/app/routes/creators.py) (planned)
- **Database Schema**: [`backend/core/directus/schemas/creator_income.yml`](../backend/core/directus/schemas/creator_income.yml)
- **YouTube Configuration**: [`backend/providers/youtube.yml`](../backend/providers/youtube.yml)

### Adding New Skills

To add creator revenue sharing to a new skill, extract the owner ID (channel ID or domain) and content ID, then create an income entry using the revenue service. See existing skill implementations for reference patterns.

For detailed technical implementation plans, see: [`docs/architecture/creators_program_implementation_plan.md`](architecture/creators_program_implementation_plan.md)

## Detailed Revenue Splits

### Web Read Skill

- **Total cost**: 20 credits per request
- **Creator**: 10 credits (50%)
- **OpenMates**: 10 credits (50%)

### Videos Get Transcript Skill

- **Total cost**: 20 credits per request
- **Creator**: 9 credits (45%)
- **YouTube**: 1 credit (5% - claimable by YouTube to cover server costs)
- **OpenMates**: 10 credits (50% - covers operational costs)

### Tips

- **100% to creator**: All tipped credits go directly to the creator
- **No platform fee**: OpenMates does not take a cut from tips

## Income Lifecycle

1. **Processing**: User processes content with a skill
2. **Reservation**: Credits are automatically reserved for the creator
3. **Claiming**: Creator signs up, verifies ownership, and claims income (coming soon)
4. **Expiration**: Unclaimed credits expire after 6 months
5. **Youth & Education Fund**: Expired credits are transferred to support educational programs

## Future Enhancements

The Creators Program is continuously evolving. Planned enhancements include:

- **Creator Account System**: Signup, verification, and income claiming functionality
- **User Tips**: Direct tipping functionality for users to support creators
- **Creator Dashboard**: Analytics and statistics for creators to view their income
- **Additional Skills**: More skills will be added to the program
- **Automated Verification**: Streamlined ownership verification process
- **Payout System**: Cash payouts (pending legal review and compliance)

## Implementation Plan

For detailed technical implementation plans and architecture decisions, see:

- [`docs/architecture/creators_program_implementation_plan.md`](architecture/creators_program_implementation_plan.md)

## Privacy and Security

### Privacy Measures

- All identifiers are anonymized before storage
- Credit amounts are securely stored
- No user tracking or personal data storage
- Creators only see aggregated statistics

### Security

- Content ownership verification required before claiming
- Secure storage of all sensitive data
- Audit logging for all creator operations

## Support

For questions about the Creators Program:

- **Creators**: Contact support through your OpenMates account
- **Developers**: See implementation plan and code references above
- **General**: Check the [OpenMates documentation](../README.md)
