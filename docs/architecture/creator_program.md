# Creator Program

## Overview

The OpenMates Creator Program ensures that content creators (website owners and video creators) are compensated when their content is processed by OpenMates skills. This program includes both automatic revenue sharing from skill usage and optional user tips.

## How It Works

### Revenue Sharing from Skill Usage

When users make requests to skills that process creator content, a portion of the credits charged to the user is automatically reserved for the creator:

#### Supported Skills

1. **Web Read** - When users read website content

   - Total cost: 20 credits
   - Creator receives: 10 credits (50%)
   - OpenMates receives: 10 credits (50%)

2. **Videos Get Transcript** - When users get transcripts from YouTube videos

   - Total cost: 20 credits
   - Creator receives: 10 credits (50%)
   - OpenMates receives: 10 credits (50%)

#### Revenue Split

The 50/50 split ensures:

- **Creators receive meaningful compensation** for their content being used
- **OpenMates covers operational costs** (API fees, infrastructure, development)
- **Fair distribution** that benefits both creators and the platform

### User Tips

Users can directly support creators by tipping them with credits:

- **100% of tipped credits go to the creator** (no platform fee)
- **Tip range**: 50 to 20,000 credits
- **Available from video embeds**: Users can tip creators directly from video embeds via the "Tip Creator" button or right-click context menu
- **Tips are reserved** for creators and can be claimed when they sign up for a creator account

## Privacy-First Design

The Creator Program is designed with privacy as a core principle:

### Anonymized Tracking

- **Owner IDs are hashed**: Channel IDs (for videos) and domains (for websites) are hashed using SHA-256 before storage
- **Content IDs are hashed**: Video IDs and URLs are hashed to track usage statistics without storing actual content identifiers
- **No user tracking**: We don't store which users processed which content - we only track that content was processed
- **Encrypted financial data**: Credit amounts are encrypted before storage

### What Creators Can See

When creators sign up and claim their account, they can see:

- **Total earnings** (aggregated from all income entries)
- **Usage statistics** (how many times their content was processed)
- **Content breakdown** (which videos/URLs were processed, without storing actual URLs)
- **Time-based analytics** (when content was processed)

### What Creators Cannot See

- **User identities**: Creators cannot see which users processed their content
- **Actual URLs/video IDs**: Only hashed identifiers are stored
- **Individual user behavior**: No tracking of individual user interactions

## Claiming Revenue

### Signup Process

1. **Creator signs up** with an OpenMates account
2. **Verification**: Creator verifies ownership of their content:
   - For YouTube creators: Verify channel ownership
   - For website owners: Verify domain ownership
3. **Account creation**: A `creator_account` entry is created linking their user ID to their hashed owner ID(s)

### Claiming Reserved Revenue

- **Automatic transfer**: When a creator account exists, credits are automatically transferred to their account in real-time
- **Reserved revenue**: If a creator hasn't signed up yet, revenue remains reserved for up to 6 months
- **Claim window**: Creators can claim revenue from up to 6 months after the content was processed
- **After 6 months**: Unclaimed revenue goes to the Youth & Education Fund

### Real-Time Credit Transfer

When a `creator_income` entry is created:

1. **Check if creator account exists** for the hashed owner ID
2. **If YES**:
   - Decrypt the reserved credits
   - Transfer credits to creator's account immediately
   - Mark income entry as "claimed"
3. **If NO**:
   - Leave status as "reserved"
   - Credits will be transferred when creator claims their account

## Youth & Education Fund

Unclaimed revenue (after 6 months) is transferred to the Youth & Education Fund:

- **Purpose**: Make OpenMates more accessible to students and young people with limited funds
- **Usage**: Funds learning workshops and educational programs organized by OpenMates
- **Impact**: Ensures that unclaimed creator revenue still benefits the community

## Credits-Only System (Current Phase)

Currently, the Creator Program operates as a **credits-only system**:

- **Creators receive credits** that can be used on the OpenMates platform
- **No cash payouts** (for legal safety and regulatory compliance)
- **Future consideration**: Cash payouts may be implemented after extensive legal review for banking/financial services regulations

## Income Sources

Creators can earn revenue from two sources:

1. **Skill Usage** (`income_source: "skill_usage"`)
   - Automatic revenue sharing when users process creator content
   - 50/50 split with OpenMates

2. **User Tips** (`income_source: "tip"`)
   - Direct tips from users who want to support creators
   - 100% of tipped credits go to the creator

## Technical Implementation

### Data Storage

- **`creator_income` collection**: Stores individual income entries with hashed identifiers and encrypted credit amounts
- **`creator_accounts` collection**: Links creator user accounts to their hashed owner IDs
- **Privacy-preserving**: All sensitive data is hashed or encrypted

### Processing Flow

1. **Skill execution**: When a skill processes creator content
2. **Async income creation**: `creator_income` entry is created asynchronously (non-blocking)
3. **Real-time transfer**: If creator account exists, credits are transferred immediately
4. **Reservation**: If no account exists, credits remain reserved for 6 months

## Future Enhancements

- **Additional skills**: More skills may be added to the Creator Program in the future
- **Cash payouts**: Research and implementation of cash payout options (pending legal review)
- **Enhanced analytics**: More detailed statistics and insights for creators
- **Creator dashboard**: Dedicated UI for creators to view earnings and manage their account

## Related Documentation

- [Creators Program Implementation Plan](./creators_program_implementation_plan.md) - Technical implementation details
