# Shopping app architecture

> This file documents the Shopping app, which can be used by asking the digital team mates in a chat and later also via the OpenMates API.

The Shopping app helps users manage products they are considering buying, track purchase decisions, and get intelligent reminders to reconsider items at appropriate times.

## Settings and Memories

### Buy List

The Buy List allows users to store products they are considering purchasing. Each entry in the buy list represents a product the user is thinking about buying, with the ability to track details, priorities, and automatically suggest reminders to reconsider the purchase decision in the future.

**Purpose**:

- Track products under consideration before making a purchase decision
- Store product details, priorities, and notes for future reference
- Enable intelligent reminder suggestions to reconsider purchase decisions at appropriate times
- Help users make more thoughtful purchasing decisions by allowing time for consideration

**Schema**:

- `product_name` (string, required): Name or description of the product
- `category` (string, optional): Product category (e.g., "electronics", "clothing", "home", "books")
- `price_range` (string, optional): Expected or known price range (e.g., "$50-100", "under $200")
- `priority` (string, optional): Priority level - one of: "high", "medium", "low" (default: "medium")
- `notes` (string, optional): Additional notes, considerations, or context about the product
- `added_date` (string, format: date, required): Date when the product was added to the buy list (YYYY-MM-DD)
- `reminder_suggested` (boolean, optional): Whether a reminder has been suggested for this item (default: false)
- `reminder_date` (string, format: date, optional): Suggested date to reconsider this purchase (YYYY-MM-DD)

**Auto-Suggest Reminder Feature**:

The system automatically suggests creating reminders to reconsider buy list items in the future. This feature helps users:

- **Revisit purchase decisions**: After some time has passed, users may have different priorities, financial situations, or needs
- **Avoid impulse purchases**: By suggesting a "cooling-off" period, users can make more deliberate decisions
- **Track changing needs**: Products that seemed important initially may become less relevant over time

**How Auto-Suggest Works**:

1. **When an item is added**: The assistant can suggest setting a reminder date based on:
   - Product category (e.g., expensive items might suggest a longer consideration period)
   - Priority level (high priority items might suggest a shorter reminder period)
   - User's purchase history and patterns (if available)
   - Default suggestion: 1-2 weeks for most items, 1 month for high-value items

2. **Reminder suggestions**: The assistant can suggest reminders like:
   - "Would you like me to remind you to reconsider this purchase in 2 weeks?"
   - "Since this is a high-value item, I can set a reminder for 1 month from now"
   - "I can create a reminder to check if you still need this product next week"

3. **Reminder creation**: When a user confirms a reminder suggestion:
   - The `reminder_date` field is set in the buy list entry
   - The `reminder_suggested` field is set to `true`
   - The system can integrate with the Reminder app to create an actual reminder notification
   - The reminder can reference the buy list entry for context

4. **Follow-up suggestions**: When a reminder date approaches or passes:
   - The assistant can proactively suggest reviewing the buy list item
   - Users can decide to purchase, remove from list, or extend the consideration period
   - The system can suggest price checking, availability updates, or alternative products

**Integration with Reminder App**:

The Shopping app can integrate with the Reminder app to create actual reminder notifications:

- When a reminder is suggested and confirmed for a buy list item, a reminder entry can be created in the Reminder app
- The reminder can include context about the product and link back to the buy list entry
- Users receive notifications at the reminder date to reconsider their purchase decision
- Reminders can be dismissed, completed (purchased), or rescheduled

**Use Cases**:

- **Product research**: Add products while researching, set reminders to make final decisions
- **Budget planning**: Track items to purchase when budget allows, with reminders to check financial situation
- **Gift ideas**: Maintain a list of potential gifts with reminders before special occasions
- **Price watching**: Track items to purchase when prices drop, with reminders to check current prices
- **Need validation**: Add items and set reminders to verify if the need still exists after time passes

**Stage**: Planning (not yet implemented)

## Future Enhancements

Potential future features:

- **Price tracking**: Integration with price comparison services to track price changes
- **Availability alerts**: Notifications when out-of-stock items become available
- **Purchase history**: Track completed purchases from the buy list
- **Budget integration**: Link buy list items to budget categories and spending limits
- **Wishlist sharing**: Share buy list items with others (e.g., for gift suggestions)
- **Product recommendations**: Suggest similar or alternative products based on buy list items
- **Category-based reminders**: Different reminder periods based on product categories
- **Priority-based sorting**: Automatically prioritize buy list items by priority and date
