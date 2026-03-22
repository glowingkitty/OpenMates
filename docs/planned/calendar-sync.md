# Calendar Sync Integration

> **Status**: 📋 Planned

## Overview
Enable calendar integration to connect OpenMates chats with calendar events, supporting both read-only reminder viewing and bi-directional event creation with Google Calendar.

## Features

### 1. ICS Calendar Support (Read-Only)
**Purpose**: Display chats with reminders in standard calendar format
- **Format**: Industry-standard ICS (iCalendar) format
- **Scope**: Read-only viewing of chat reminders
- **Use Case**: Users can subscribe to OpenMates chat reminders in any calendar app
- **Export**: Generate ICS feed of chats where user has set reminders

### 2. Google Calendar Integration (Bi-Directional)
**Purpose**: Two-way sync between OpenMates and Google Calendar

#### 2.1 Read Reminders
- Import existing calendar events as chat reminders
- Sync reminder times with calendar event times
- Update chat reminder status when calendar events change

#### 2.2 Create Chats from Calendar Events
- **Trigger**: Mention "@OpenMates" in Google Calendar event description
- **Action**: Automatically create new OpenMates chat for that calendar entry
- **Context**: Chat inherits event title, description, attendees, and timing
- **Sync**: Chat updates reflect back to calendar event (optional)

## Technical Implementation

### ICS Calendar Generation
```
GET /api/calendar/ics/{user_id}
- Authentication: User token or calendar-specific token
- Response: ICS format with chat reminders as events
- Caching: Update on reminder changes
```

### Google Calendar Integration
```
OAuth 2.0 Flow:
1. User authorizes Google Calendar access
2. Store refresh token securely
3. Periodic sync via background tasks

API Endpoints:
- POST /api/calendar/google/connect - OAuth flow
- GET /api/calendar/google/events - Fetch events
- POST /api/calendar/google/webhook - Event change notifications
```

### Data Model Extensions
```sql
-- New table for calendar integrations
calendar_integrations:
- user_id (FK)
- provider (enum: google, ics)
- access_token (encrypted)
- refresh_token (encrypted)
- webhook_id (for Google notifications)
- last_sync_at
- settings (JSON)

-- Link chats to calendar events
chat_calendar_events:
- chat_id (FK)
- calendar_event_id (external ID)
- provider
- sync_direction (enum: read_only, bi_directional)
```

## User Experience

### ICS Calendar Setup
1. User navigates to Settings → Calendar
2. Toggle "Enable ICS Calendar"
3. Copy generated ICS URL
4. Subscribe in preferred calendar app
5. View chat reminders as calendar events

### Google Calendar Setup
1. Navigate to Settings → Calendar → Google Calendar
2. Click "Connect Google Calendar"
3. Complete OAuth authorization
4. Configure sync preferences:
   - Import existing events as reminders
   - Enable @OpenMates mention detection
   - Set sync frequency

### Creating Chats from Calendar
1. Create/edit Google Calendar event
2. Add "@OpenMates" anywhere in event description
3. OpenMates automatically creates chat with:
   - Title: Event title
   - Initial message: Event description (minus @OpenMates)
   - Participants: Event attendees (if they have OpenMates accounts)
   - Reminder: Set to event start time

## Security Considerations

### Data Privacy
- Calendar tokens stored encrypted in Vault
- ICS feeds require authentication
- Users control which chats are included in calendar sync

### Permission Model
- Granular calendar permissions (read vs. read/write)
- Users can revoke calendar access anytime
- Audit log for calendar-triggered actions

### Rate Limiting
- Google Calendar API rate limits respected
- Batch operations for efficiency
- Webhook-driven updates preferred over polling

## Integration Points

### Backend Apps
- **Core API**: Calendar endpoints and OAuth handling
- **AI App**: Process @OpenMates mentions in event descriptions
- **Sync Service**: Real-time updates between calendar and chats

### Frontend
- **Settings Panel**: Calendar integration management
- **Chat Interface**: Show calendar event context when chat was created from event
- **Reminder UI**: Enhanced with calendar event details

### External Services
- **Google Calendar API**: Primary integration
- **ICS Standard**: Broad calendar app compatibility
- **Webhook Services**: Real-time event change notifications

## Future Enhancements

### Phase 2 Features
- **Multiple Calendar Support**: Outlook, Apple Calendar, CalDAV
- **Smart Scheduling**: AI suggests meeting times based on chat context
- **Calendar Templates**: Pre-configured event types that create specific chat types
- **Team Calendars**: Shared calendar integration for team workspaces

### Advanced Features
- **Meeting Summaries**: Auto-generate meeting notes in linked chats
- **Action Items**: Extract tasks from calendar events into chat todos
- **Availability Sharing**: Show calendar availability in chat contexts
- **Location Integration**: GPS-based chat reminders for location-based events

## Implementation Dependencies

### Required Services
- Google Calendar API access
- OAuth 2.0 implementation
- Webhook infrastructure for real-time updates
- ICS generation library

### Backend Changes
- New calendar service module
- Database schema updates
- Background task queue for sync operations
- Enhanced security for external API tokens

### Frontend Changes
- Calendar settings interface
- Chat creation flow updates
- Reminder UI enhancements
- OAuth flow handling