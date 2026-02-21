# Gift Cards Architecture

## Overview

OpenMates supports gift cards that can be redeemed for credits. Gift cards are single-use only and are deleted from the system after redemption. They can have any credits value from 1 to 50,000 credits, allowing for flexible gift amounts beyond standard credit packages.

## Gift Card Schema

Gift cards are stored in the `gift_cards` collection in Directus with the following structure:

```yaml
gift_cards:
  - id: uuid (primary key)
  - code: string (unique, manually entered)
  - credits_value: integer (1-50000)
  - created_at: datetime
  - notes: textfield (nullable, for admin notes)
```

### Key Fields

- **code**: Unique gift card code, manually entered in Directus UI. Used for redemption.
- **credits_value**: The number of credits this gift card provides (1-50000).

**Note**: Gift cards are deleted from both cache and Directus immediately after redemption. Redemption information is logged to compliance logs for audit purposes.

## Caching Mechanism

Gift cards are preloaded into cache on server startup for fast lookups:

1. **Preload on Startup**: All gift cards are loaded from Directus and cached on server startup (redeemed cards are deleted, so all found cards are available).
2. **Cache Key Format**: `gift_card:{code}`
3. **Cache-First Lookup**: When redeeming, the system checks cache first, then falls back to Directus if not found.
4. **Cache Invalidation**: When a gift card is redeemed, it's immediately deleted from both cache and Directus.

### Preload Function

The `preload_gift_cards()` function in `backend/core/api/main.py`:
- Fetches all gift cards from Directus (redeemed cards are deleted, so all found cards are available)
- Caches each card with key `gift_card:{code}`
- Logs the number of cards preloaded
- Runs during server startup in the `lifespan()` function

## Redemption Flow

### Backend API Endpoint

**POST** `/api/v1/payments/redeem-gift-card`

**Request:**
```json
{
  "code": "GIFT123ABC"
}
```

**Response (Success):**
```json
{
  "success": true,
  "credits_added": 5000,
  "current_credits": 15000,
  "message": "Gift card redeemed successfully! 5,000 credits added to your account."
}
```

**Response (Error):**
```json
{
  "success": false,
  "credits_added": 0,
  "current_credits": 10000,
  "message": "Invalid gift card code or code has already been redeemed"
}
```

### Redemption Process

1. **Code Validation**: Code is normalized (trimmed, uppercased)
2. **Cache Lookup**: Check cache first for the gift card
3. **Directus Fallback**: If not in cache, query Directus
4. **Validation**: Verify card exists and has valid credits value
5. **Credit Addition**: Add credits to user's account (encrypted in Directus, plaintext in cache)
6. **Card Deletion**: Delete gift card from both cache and Directus (single-use)
7. **Compliance Logging**: Log redemption to compliance logs for audit purposes
8. **WebSocket Broadcast**: Broadcast credit update to all user's devices
9. **Response**: Return success/error response

### Credit Addition Logic

Credits are added using the same pattern as payment webhooks:
- Get current credits from cache
- Calculate new total
- Encrypt new balance for Directus storage
- Update Directus user record
- Update cache with new balance
- Broadcast via WebSocket

## Frontend Integration

### Component Structure

1. **SettingsBuyCredits.svelte**: Main component that shows credit tiers or gift card input
   - Toggle between credit selection and gift card redemption
   - "I have a gift card" button to switch modes

2. **GiftCardRedeem.svelte**: Dedicated component for gift card redemption
   - Input field for gift card code
   - Redeem and Cancel buttons
   - Error and success message display
   - Loading states during redemption

### User Flow

1. User navigates to Settings > Billing > Buy Credits
2. User clicks "I have a gift card" button
3. Credit tier selection is hidden, gift card input form is shown
4. User enters gift card code
5. User clicks "Redeem code"
6. On success: Navigate to confirmation screen
7. On error: Show error message, allow retry or cancel
8. User can click "Cancel" to return to credit tier selection

### API Integration

The frontend uses the `apiEndpoints.payments.redeemGiftCard` endpoint:
- Makes POST request with gift card code
- Handles success/error responses
- Updates user profile store with new credit balance
- Credits are also updated via WebSocket `user_credits_updated` event

## Creating Gift Cards in Directus

Gift cards are created manually in the Directus web UI:

1. Navigate to the `gift_cards` collection
2. Click "Create Item"
3. Enter the following:
   - **code**: Unique gift card code (manually entered, e.g., "GIFT2024ABC123")
   - **credits_value**: Number of credits (1-50000)
   - **notes**: Optional admin notes (e.g., "Birthday gift for John")
4. Save the gift card
5. The gift card will be automatically cached on next server restart

### Best Practices

- Use clear, memorable codes (e.g., "BIRTHDAY2024" or "GIFT-ABC-123")
- Codes are case-insensitive (stored uppercase)
- Avoid codes that could be easily guessed
- Document the purpose in the `notes` field

## Credit Value Limits

- **Minimum**: 1 credit
- **Maximum**: 50,000 credits
- **Flexibility**: Unlike credit packages, gift cards can have any value in this range

This allows for:
- Custom gift amounts
- Promotional campaigns
- Special offers
- Bulk purchases

## Security Considerations

1. **Single-Use**: Gift cards are deleted after redemption to prevent reuse
2. **Directus Fallback**: If cache is cleared, Directus is checked to prevent double redemption
3. **User Authentication**: Redemption requires authenticated user session
4. **Code Normalization**: Codes are normalized (uppercase, trimmed) to prevent case-sensitivity issues
5. **Compliance Logging**: All redemptions are logged to compliance logs for audit and regulatory requirements

## Error Handling

### Invalid Code
- Code not found in cache or Directus
- Response: "Invalid gift card code or code has already been redeemed"

### Already Redeemed
- Code not found in cache or Directus (redeemed cards are deleted)
- Response: "Invalid gift card code or code has already been redeemed"

### Invalid Credits Value
- Gift card has invalid or zero credits value
- Response: "Invalid gift card: credits value is invalid"

### Database Errors
- If Directus update fails after credits are added to cache, an error is raised
- Credits are still added (cache is source of truth for balance)

## Monitoring and Logging

All gift card operations are logged:
- **Preload**: Number of gift cards loaded into cache
- **Redemption Attempts**: User ID, code, success/failure
- **Compliance Logs**: All successful and failed redemptions are logged to compliance logs for audit purposes
  - Includes: user_id, gift_card_code, credits_added, previous_credits, new_credits
  - Stored in `compliance.log` with long-term retention for regulatory compliance
- **Errors**: Detailed error messages for debugging

## Future Enhancements

Potential improvements:
- Gift card expiration dates (optional)
- Bulk gift card generation
- Gift card analytics (redemption rates, etc.)
- Email notifications when gift cards are redeemed
- Gift card purchase flow (allow users to buy gift cards for others)

