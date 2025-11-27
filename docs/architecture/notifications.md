# Notifications architecture

![Notifications](../images/notifications.jpg)

## Overview

The notification system provides web app notifications (toasts/alerts) and PWA (Progressive Web App) system notifications for the web app. All notification types use the same shared `Notification.svelte` component for consistent UI/UX.

**Current Scope**: Notifications are currently implemented only for the web app/PWA.

**Future Scope**: There is an option to add notification support to CLI/pip/npm packages in the future, which would allow programmatic access to notifications for developers and system administrators.

## Implementation

### Shared Component

All notifications are rendered using the shared `Notification.svelte` component located at `frontend/packages/ui/src/components/Notification.svelte`. The component uses a card-based design with the following structure:

- **Header**: Notification title with a bell icon on the left, and a close button in the top right corner
- **Main Icon**: Located on the left side of the card:
  - For message notifications: Profile picture with optional badge (e.g., star icon)
  - For system notifications: Purple system icons (logout arrow, disconnected chain, download arrow, etc.)
- **Message**: Formatted text on the right side with:
  - Bold text styling
  - Blue text for important/actionable parts
  - Black text for regular content
  - Multi-line support for longer messages
- **Close Button**: Located in the top right corner of each notification, allows users to dismiss individual notifications
- **Message Input** (for message notifications only):
  - A "Click here to respond" field at the bottom of the notification, spanning the full width of the notification card
  - On click, expands to show the full message input field inside the notification
  - Uses the same message input component as ActiveChat, providing consistent functionality for responding directly from notifications

Notifications are displayed as stacked cards with white backgrounds, rounded corners, and appear at the top of the main content area. The component is managed through the `notificationStore` which provides a centralized way to add, remove, and manage notifications across the application.

### Notification Types

#### Initial Implementation

The following notification types are implemented initially:

1. **New message completed in chat**
   - Triggered when a chat message response is completed
   - Displays profile picture of the sender with optional badge
   - Provides user feedback that their message has been processed
   - Includes a "Click here to respond" field at the bottom that expands to show the full message input field (same component as used in ActiveChat)
   - Allows users to respond directly from the notification without navigating to the chat

2. **Auto logout**
   - Triggered when the user is automatically logged out (e.g., due to session expiration, security reasons)
   - Uses logout icon (purple arrow exiting square)
   - Message suggests activating "Stay logged in" during login to remain connected

#### Future Additions

Additional notification types to be implemented over time:

1. **Software update available**
   - **Server admins only**: Only shown to users with administrative privileges
   - Uses download icon (purple arrow pointing down into square)
   - Notifies admins when a new software version is available (e.g., "OpenMates v0.3 is available now. Check your server settings to install it.")

2. **Can't connect to server**
   - Uses disconnected/broken chain icon (purple)
   - Triggered when connection to the server is lost
   - Message format: "Trying to reconnect for 30 seconds. Else Offline Mode will be activated."
   - Behavior depends on user's login preferences:
     - **If user selected "stay logged in" during login**:
       - Informs user about connection loss and reconnection attempt
       - Notifies that offline mode will be activated if reconnection fails
       - Allows continued use of the application in offline mode
     - **If user did NOT select "stay logged in"**:
       - User is automatically logged out once connection drops
       - If connection cannot be re-established after a few seconds, user is logged out
       - Notification informs user about the logout and connection issues

3. **Security notifications** (future)
   - Examples:
     - Login from other device
     - Suspicious activity detected
     - Password change notifications
     - Two-factor authentication events

## PWA Notifications

For the Progressive Web App (PWA) implementation, we utilize native browser notification APIs to provide system-level notifications for important events. This ensures users receive notifications even when the application is not in focus.

### Platform Support

- **Web/Android**: Uses the standard Web Notifications API
- **iOS**: Apple has its own implementation for PWA notifications (requires specific configuration and user permission)

### Important Notifications (PWA)

The following notification types trigger PWA system notifications (in addition to web app notifications):

1. **New message completed in chat** - Users receive a system notification when their chat message is completed, allowing them to return to the conversation
2. **Software update available** - Server admins receive system notifications for critical updates
3. **Security-related notifications** (future) - Important security events like logins from other devices will trigger system notifications

### Reply to Notification (Future Enhancement)

We plan to add support for direct replies to notifications at the OS level via PWA functionality on supported platforms. This will allow users to respond to messages directly from system notifications without switching back to the application.

**Planned Features**:
- **macOS**: Users will be able to see notifications in the macOS notification center and reply directly to messages
- **Windows**: Similar reply functionality for Windows system notifications
- **Android**: Reply action for Android system notifications
- **Fallback**: On platforms without native reply support, notifications will open the relevant chat when clicked

**Implementation Approach**:
- Utilize the Notification API's `actions` property to add a reply action button
- Integrate with platform-specific notification features (e.g., reply boxes in macOS and Windows)
- Send the reply directly to the server with context about which chat/conversation it belongs to
- Provide visual feedback to confirm the message was sent

### Implementation Notes

- PWA notifications require user permission (requested on first use)
- Notifications should be actionable when possible (e.g., clicking a notification opens the relevant chat or page)
- Notification content should be concise but informative
- Respect user preferences for notification types (users may want to disable certain notification categories)
- Reply-to-notification will be prioritized for message notifications first, with potential expansion to other notification types

## Integration with PWA & Offline Support

Notifications are implemented together with PWA (Progressive Web App) and offline support for the web app. This allows:

- Notifications to work even when the app is in the background
- Offline mode notifications to inform users about connection status
- Cross-platform consistency in notification behavior (including iOS devices via PWA)

## Use Cases

### Responses to User Messages

Notifications are used to inform users when their messages have been processed and responses are ready, providing immediate feedback and improving user experience.

### Optional Social Media Posts & Promotions

Notifications can be used for optional social media posts and promotions, allowing users to directly ask questions or start conversations from these notifications. This provides an alternative to traditional social media or email for users who prefer not to use those platforms.

### Alternative Communication Channel

The notification system serves as an alternative to social media and email for users who prefer not to use those platforms, providing a direct communication channel within the application.
