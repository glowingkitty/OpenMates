# Account Deletion Architecture

> planned architecture 

## Overview

This document describes the architecture for user account deletion, including the deletion flow, data cleanup, refund processing, and compliance requirements.

## User Flow

### 1. Account Deletion Preview

**Location**: Settings → Account → Delete Account

**Before showing deletion form, fetch deletion preview**:
- Call `GET /api/v1/settings/delete-account-preview` to get:
  - Credits older than 14 days (if any exist)
  - Auto-refund information (eligible purchases from last 14 days)
  - Gift card purchases that will be deleted

**Display Logic**:
- **Credits Loss Warning**: Only show if `credits_older_than_14_days > 0`
  - Display: "You will lose {count} credits that are older than 14 days"
  - Show confirmation toggle: "I understand that I will lose {count} credits older than 14 days"
- **Auto-Refund Information**: Show if any eligible refunds exist
  - Display summary of refunds that will be processed:
    - Number of invoices eligible for refund
    - Total refund amount (in currency)
    - Total unused credits to be refunded
    - Gift card purchases that will be deleted (cannot be refunded once used)
- **Data Deletion Warning**: Always show
  - Confirmation toggle: "I understand that all my data will be permanently deleted and cannot be recovered, including chats, embeds, uploaded files, settings, memories, etc."

### 2. Account Deletion Request

**Requirements**:
- User must authenticate again before deletion (passkey or 2FA OTP, depending on what they have set up)
- User must confirm required toggles:
  1. **Loss of Credits** (conditional): Only required if `credits_older_than_14_days > 0`
  2. **Data Deletion**: Always required

### 3. Immediate Response

Upon successful deletion request:
- User is immediately logged out on all devices
- User sees success notification: "Your account got deleted successfully"
- Celery task is triggered to process deletion asynchronously
- User cannot log back in (authentication data deleted first)

### 4. Asynchronous Processing

The actual deletion happens via Celery task to avoid blocking the user response. The task processes deletion in priority order (see below).

## Priority Deletion Order

**Critical**: Authentication data must be deleted FIRST to prevent user from logging back in during deletion process.

### Phase 1: Authentication Data (Highest Priority)

1. **Passkeys** (`user_passkeys` collection)
   - Delete all passkeys for user (`user_id` or `hashed_user_id`)

2. **API Keys** (`api_keys` collection)
   - Delete all API keys for user (`user_id` or `hashed_user_id`)
   - Delete associated `api_key_devices` records

3. **2FA Data** (in `directus_users` record)
   - `encrypted_tfa_secret`
   - `tfa_backup_codes_hashes`
   - `encrypted_tfa_app_name`
   - `tfa_last_used`
   - `consent_tfa_safely_stored_timestamp`

4. **Lookup Hashes** (in `directus_users` record)
   - `lookup_hashes` array (used for zero-knowledge authentication)

5. **Email Authentication Data** (in `directus_users` record)
   - `hashed_email`
   - `user_email_salt`
   - `encrypted_email_address`
   - `encrypted_email_with_master_key`

6. **Vault Keys**
   - Delete encryption keys from Vault (`vault_key_id`, `vault_key_version`)
   - Delete encryption keys from `encryption_keys` collection linked to user's API keys

7. **Sessions & Tokens**
   - Logout all sessions via Directus API
   - Clear all session tokens from Redis cache
   - Send logout requests to all connected WebSocket devices

### Phase 2: Payment & Subscription Data

8. **Stripe Cleanup**
   - Cancel active subscription (`stripe_subscription_id`) if exists
   - Delete Stripe customer (`stripe_customer_id`) if exists
   - Note: Payment methods are encrypted; Stripe-side cleanup may be needed

9. **Auto-Refund Processing** (Purchases from last 14 days)
   - Find all invoices from last 14 days (`date >= now() - 14 days`)
   - For each eligible invoice:
     - Check if refund is valid:
       - Invoice is not already refunded (`refunded_at` is null)
       - Invoice is not a gift card purchase (`is_gift_card` is false)
       - Invoice has unused credits (calculate: `total_credits - used_credits`)
     - If valid:
       - Calculate refund amount (proportional to unused credits)
       - Process refund via payment provider (Stripe/Revolut)
       - Update invoice with `refunded_at`, `encrypted_refunded_credits`, `encrypted_refund_amount`, `refund_status = "completed"`
       - Log refund via `ComplianceService.log_refund_request()`
       - Update user credits (subtract refunded credits)
   - **Note**: Credits from purchases older than 14 days are NOT refunded and will be lost

10. **Gift Cards**
    - Delete purchased gift cards (`gift_cards` where `purchaser_user_id_hash` matches user)
    - Delete redemption records (`redeemed_gift_cards` where `user_id_hash` matches user)
    - **Note**: Gift cards cannot be refunded once they have been used/redeemed

11. **Invoices**
    - Delete all invoices (`invoices` where `user_id_hash` matches user)
    - Delete invoice PDFs from S3 (using `encrypted_s3_object_key`)

### Phase 3: User Content & Data

12. **Chats & Messages**
    - Delete all chats created by user (`chats` where `user_id` matches)
    - Delete all messages by user (`messages` where `user_id` matches)
    - Delete all embeds by user (`embeds` where `user_id` matches)
    - Note: Cascade deletion may handle some relationships automatically

13. **Usage Data**
    - Delete all usage entries (`usage` where `user_id_hash` matches user)
    - Delete usage summaries:
      - `usage_monthly_chat_summaries` (where `user_id_hash` matches)
      - `usage_monthly_api_key_summaries` (where `user_id_hash` matches)

14. **App Settings & Memories**
    - Delete all app settings/memories (`user_app_settings_and_memories` where `hashed_user_id` matches user)

15. **User Files** (Future Implementation)
    - Delete uploaded files from S3:
      - Profile images
      - Other user-uploaded files
    - Note: Marked as "later" - not yet implemented

### Phase 4: Cache Cleanup

16. **Redis Cache**
    - User profile: `user_profile:{user_id}`
    - User devices: `user_device:{user_id}:*`
    - User device lists: `user_device_list:{user_id}`
    - User sessions: `session:*` (filter by user_id)
    - Chat-related caches:
      - `user:{user_id}:chat_ids_versions`
      - `user:{user_id}:chat:{chat_id}:*` (all chat keys)
      - `user:{user_id}:active_chats_lru`
      - `user:{user_id}:chats`
    - App settings/memories cache: `user:{user_id}:chat:{chat_id}:app:{app_id}:*`
    - Order status cache: `order_status:*` (filter by user)
    - Gift card cache: `gift_card:{code}` (for purchased cards)

### Phase 5: User Record & Compliance

17. **Compliance Logging**
    - Log account deletion via `ComplianceService.log_account_deletion()`
    - Include: `user_id`, `deletion_type="user_requested"`, `reason`, `ip_address`, `device_fingerprint`

18. **User Record Deletion**
    - Delete user record from `directus_users` collection
    - This is the final step after all related data is deleted

## Implementation Details

### Celery Task Structure

```python
@celery_app.task(name="delete_user_account")
def delete_user_account_task(
    user_id: str,
    deletion_type: str = "user_requested",
    reason: str = "User requested account deletion",
    ip_address: str = None,
    device_fingerprint: str = None,
    refund_invoices: bool = True  # Auto-refund purchases from last 14 days
):
    """
    Asynchronously delete user account and all associated data.
    
    Processes deletion in priority order:
    1. Authentication data (prevents re-login)
    2. Payment/subscription data (with auto-refunds)
    3. User content (chats, messages, embeds)
    4. Cache cleanup
    5. User record deletion
    
    Args:
        user_id: ID of user to delete
        deletion_type: Type of deletion (user_requested, policy_violation, admin_action)
        reason: Reason for deletion
        ip_address: IP address of deletion request
        device_fingerprint: Device fingerprint of deletion request
        refund_invoices: Whether to auto-refund eligible purchases from last 14 days
    """
    # Implementation follows priority order above
    pass
```

### API Endpoints

#### GET `/api/v1/settings/delete-account-preview`

**Purpose**: Get preview information about what will happen during account deletion.

**Response**:
```json
{
  "credits_older_than_14_days": 5000,
  "has_credits_older_than_14_days": true,
  "auto_refunds": {
    "total_refund_amount_cents": 2000,
    "total_refund_currency": "eur",
    "total_unused_credits": 10000,
    "eligible_invoices": [
      {
        "invoice_id": "uuid",
        "order_id": "order_123",
        "date": "2024-01-15T10:00:00Z",
        "total_credits": 15000,
        "unused_credits": 10000,
        "refund_amount_cents": 2000,
        "currency": "eur",
        "is_gift_card": false
      }
    ],
    "gift_card_purchases": [
      {
        "gift_card_code": "GIFT-ABC123",
        "credits_value": 5000,
        "purchased_at": "2024-01-10T10:00:00Z",
        "is_redeemed": false
      }
    ]
  },
  "has_auto_refunds": true
}
```

**Calculation Logic**:
1. **Credits Older Than 14 Days**:
   - Get all invoices older than 14 days (`date < now() - 14 days`)
   - For each invoice, calculate unused credits: `total_credits - used_credits`
   - Sum all unused credits from invoices older than 14 days
   - Note: Only credits from purchases older than 14 days are lost (credits from recent purchases are refunded)

2. **Auto-Refund Eligibility**:
   - Find all invoices from last 14 days (`date >= now() - 14 days`)
   - For each invoice:
     - Check if already refunded (`refunded_at` is null)
     - Check if not a gift card purchase (`is_gift_card` is false)
     - Calculate unused credits: `total_credits - used_credits`
     - If unused credits > 0, calculate refund amount
   - Sum total refund amounts and unused credits

3. **Gift Card Purchases**:
   - Find all gift cards purchased by user (`purchaser_user_id_hash` matches)
   - Check if each gift card is redeemed
   - Note: Unredeemed gift cards will be deleted (cannot be refunded once used)

#### POST `/api/v1/settings/delete-account`

**Request Body**:
```json
{
  "confirm_credits_loss": true,  // Only required if credits_older_than_14_days > 0
  "confirm_data_deletion": true,  // Always required
  "auth_method": "passkey" | "2fa_otp",
  "auth_code": "..." // OTP code if using 2FA
}
```

**Response** (immediate):
```json
{
  "success": true,
  "message": "Account deletion initiated. You will be logged out shortly."
}
```

**Flow**:
1. Validate authentication (passkey or 2FA OTP)
2. Validate required confirmation toggles:
   - `confirm_data_deletion` must be `true` (always required)
   - `confirm_credits_loss` must be `true` only if user has credits older than 14 days
3. Trigger Celery task with deletion details
4. Logout user immediately
5. Return success response

### Device Logout

When account deletion is initiated:
1. Send logout message to all connected WebSocket devices via `ConnectionManager.broadcast_to_user()`
2. Message type: `account_deleted`
3. All devices receive logout signal and clear local data
4. Server-side: Logout all sessions via `DirectusService.logout_all_sessions()`

### Credits Calculation Logic

**Credits Older Than 14 Days**:
- Purpose: Identify credits that will be lost (not eligible for refund)
- Calculation:
  1. Get all invoices older than 14 days (`date < now() - 14 days`)
  2. For each invoice:
     - Decrypt `encrypted_credits_purchased` to get `total_credits`
     - Get all usage entries created after invoice date
     - Sum credits from usage entries to get `used_credits`
     - Calculate `unused_credits = total_credits - used_credits`
  3. Sum all `unused_credits` from invoices older than 14 days
- Display: Only show warning if `credits_older_than_14_days > 0`
- Example: If user has 5,000 unused credits from a purchase 20 days ago, they will lose those credits

**Current Credit Balance**:
- The user's current credit balance includes:
  - Credits from purchases older than 14 days (will be lost)
  - Credits from purchases within 14 days (will be refunded if unused)
  - Credits from gift card redemptions (cannot be refunded)
  - Credits from subscription renewals (cannot be refunded)

### Auto-Refund Logic

**Eligibility Criteria**:
- Invoice date is within last 14 days (`date >= now() - 14 days`)
- Invoice is not already refunded (`refunded_at` is null)
- Invoice is not a gift card purchase (`is_gift_card` is false)
- Invoice has unused credits (calculated: `total_credits - used_credits`)

**Refund Calculation**:
- Calculate unused credits: `total_credits - used_credits`
- Calculate unit price: `total_amount_cents / total_credits`
- Refund amount: `unused_credits * unit_price_per_credit`

**Refund Process**:
1. Process refund via payment provider (Stripe/Revolut)
2. Update invoice with refund details
3. Update user credits (subtract refunded credits)
4. Log refund via `ComplianceService.log_refund_request()`
5. Generate credit note PDF (if applicable)

**Gift Card Purchases**:
- Gift cards purchased within 14 days cannot be refunded once used/redeemed
- Unredeemed gift cards will be deleted (cannot be refunded)
- Display information about gift card purchases that will be deleted

### Error Handling

**Partial Failures**:
- If deletion fails at any phase, log error but continue with remaining phases
- Critical: Authentication data deletion must succeed before proceeding
- Non-critical failures (e.g., S3 file deletion) should not block account deletion

**Retry Logic**:
- Authentication data deletion: Retry up to 3 times (critical)
- Payment provider operations: Retry up to 2 times
- Cache cleanup: Retry up to 2 times
- Other operations: Single attempt (failures logged but don't block)

**Monitoring**:
- Log all deletion steps with timestamps
- Alert on critical failures (authentication data deletion)
- Track deletion completion time
- Monitor refund processing success rate

## Data Deletion Checklist

### Directus Collections
- [ ] `directus_users` - User record (deleted last)
- [ ] `chats` - All user's chats
- [ ] `messages` - All user's messages
- [ ] `embeds` - All user's embeds
- [ ] `usage` - All usage entries
- [ ] `usage_monthly_chat_summaries` - Chat usage summaries
- [ ] `usage_monthly_api_key_summaries` - API key usage summaries
- [ ] `user_passkeys` - All passkeys
- [ ] `api_keys` - All API keys
- [ ] `api_key_devices` - API key devices
- [ ] `invoices` - All invoices
- [ ] `gift_cards` - Purchased gift cards
- [ ] `redeemed_gift_cards` - Redemption records
- [ ] `user_app_settings_and_memories` - App settings/memories
- [ ] `encryption_keys` - Encryption keys for API keys

### External Services
- [ ] Vault - User encryption keys
- [ ] Stripe - Cancel subscription, delete customer
- [ ] S3 - Invoice PDFs (and uploaded files - future)

### Redis Cache
- [ ] User profile cache
- [ ] User device caches
- [ ] User session caches
- [ ] Chat-related caches
- [ ] App settings/memories cache
- [ ] Order status cache
- [ ] Gift card cache

### Compliance
- [ ] Log account deletion via `ComplianceService.log_account_deletion()`

## Security Considerations

1. **Authentication Validation**: User must re-authenticate before deletion (prevents unauthorized deletion)
2. **Confirmation Toggles**: User must explicitly confirm data loss (prevents accidental deletion)
3. **Priority Deletion**: Authentication data deleted first (prevents re-login during deletion)
4. **Device Logout**: All devices logged out immediately (prevents continued access)
5. **Compliance Logging**: All deletions logged for audit purposes

## Future Enhancements

1. **File Deletion**: Implement S3 file deletion for uploaded files
2. **Deletion Queue**: Implement queue system for large accounts with many records
3. **Deletion Status**: Allow users to check deletion status (before logout)
4. **Grace Period**: Optional grace period before permanent deletion (e.g., 30 days)
5. **Data Export**: Allow users to export data before deletion

## Related Documentation

- [Payment Processing Architecture](./payment_processing.md) - Refund policies
- [Security Architecture](./security.md) - Encryption and authentication
- [Compliance Service](../backend/core/api/app/services/compliance.py) - Logging requirements
- [Cache Architecture](./cache_architecture.md) - Cache cleanup patterns

