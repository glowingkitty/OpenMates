# App Store

The App Store is a submenu in the Settings interface that allows users to explore and discover available apps, similar to mobile app stores. It provides a comprehensive view of all apps, their capabilities, pricing, and features.

## Overview

The App Store is accessible through the Settings menu (`Settings > App Store`) and provides users with:

- **App Discovery**: Browse all available apps in an organized, visually appealing interface
- **Skill Information**: View all skills available for each app
- **Pricing Details**: See the cost (in credits) for each skill
- **Focus Modes**: Discover available focus modes for each app
- **Provider Information**: Learn which external providers are used by each app skill

## User Interface

The App Store interface is designed to be intuitive and similar to familiar mobile app store experiences:

- **App Cards**: Each app is displayed as a card with:
  - App icon and name
  - Brief description
  - Installation status (installed by default, can be uninstalled)

- **App Details View**: Clicking on an app card opens a detailed view showing:
  - Full app description
  - Install/Uninstall button (all apps installed by default)
  - Complete list of skills with:
    - Skill name and description
    - Pricing information (costs shown per skill, and per model/provider when applicable)
    - Confirmation requirement setting (default and user override)
    - Supported providers
    - Skill status (production/development)
  - Available focus modes with descriptions
  - App-specific settings and memories (if applicable)
  - Connected accounts (if applicable): Shows which external accounts can be connected (e.g., Figma, Gmail) and their connection status

## Features

### App Browsing

Users can browse apps by:

- **Category**: Apps are organized into categories such as:
  - **Top picks for you**: Personalized recommendations based on conversation context and app usage patterns. Only shown to authenticated users. For new users or users without recommendations, random apps are shown as a fallback.
  - **Most used**: Most popular apps based on usage in the last 30 days across all users. Shows the top 5 most frequently used apps. This section uses anonymous analytics data (no user-specific information). Data is fetched on app load to ensure it's available when the App Store opens.
  - **New apps**: Recently added apps
  - **For work**: Productivity and professional tools (e.g., Code, Email)
  - **For everyday life**: General purpose apps (e.g., Videos, Calendar)
  - Additional categories may be added as the app ecosystem grows
  - **Note**: Apps can appear in multiple categories (duplicates allowed)
- **Status**: Filter by production-ready apps or include development apps
- **Search**: Search for apps by name, description, or skill name

### Skill Information

For each skill, users can see:

- **Name and Description**: What the skill does
- **Pricing**: Cost in credits shown per skill, and per model/provider when applicable (e.g., different costs for different AI models or API providers)
- **Providers**: Which external services are used (e.g., Brave Search, YouTube API, OpenAI)
- **Usage Examples**: Example use cases for the skill

### Focus Mode Discovery

Users can discover focus modes available for each app:

- **Focus Mode Name**: Clear, descriptive name
- **Description**: What the focus mode does and when to use it
- **System Prompt**: The system prompt for the focus mode
- **Related Skills**: Which skills the focus mode typically uses

### Provider Information

The App Store shows which external providers are used by each skill:

- **Provider Name**: The service or API being used
- **Provider Type**: Search engine, API service, etc.
- **Privacy Notes**: Information about data handling and privacy

### Connected Accounts

For apps that require external account connections (e.g., Figma, Gmail, Calendar services), the App Store displays:

- **Available Connections**: Which external services can be connected
- **Connection Status**: Whether accounts are currently connected
- **Connection Method**: OAuth 2.0 or API key authentication
- **Required Permissions**: What access the app needs from the connected account
- **Manage Connections**: Quick access to connect, disconnect, or update account credentials

## Integration with Settings

The App Store is integrated into the Settings menu structure:

- **Access Path**: `Settings > App Store`
- **Navigation**: Users can navigate back to main settings or to other settings sections
- **Deep Linking**: Direct links to specific apps or skills can be shared

## Implementation Status

> **Note**: The App Store UI is currently in development. The SettingsApps component exists as a placeholder and will be fully implemented in a future release.

**Planned Features:**

- App browsing interface with cards and categories
- Detailed app views with skill and focus mode information
- Search and filtering capabilities
- Pricing display for each skill
- Provider information for transparency

## App Installation Model

**Default State**: All apps are installed and available by default

- **Installed by Default**: All apps appear as "installed" in the App Store
- **Uninstall Action**: Users can uninstall apps by clicking "Uninstall" in the App Store
- **Uninstalled Apps**: Removed from the list of allowed apps and ignored during message processing
- **Reinstall**: Users can reinstall uninstalled apps at any time from the App Store

**Message Processing Integration:**

- Uninstalled apps are excluded from tool preselection during message processing
- The LLM will not attempt to use skills from uninstalled apps
- This prevents errors and ensures users only see functionality for apps they want to use

## Data Source

The App Store displays information from:

- **App Metadata**: Each app's `app.yml` file contains:
  - App name, description, icon
  - Skills definitions with pricing and default confirmation requirements
  - Focus mode definitions
  - Provider information

- **Build-Time Generation**: App metadata is generated at build time from all `app.yml` files in `backend/apps/`:
  - **Build Script**: `frontend/packages/ui/scripts/generate-apps-metadata.js`
  - **Generated File**: `frontend/packages/ui/src/data/appsMetadata.ts`
  - **Filtering**: Only production-stage skills are included (development skills are filtered out)
  - **Build Integration**: The script runs automatically during the build process via `prebuild` hook in `package.json`
  - **Offline-First**: This allows offline browsing of the App Store (offline-first PWA architecture)
  - **Manual Generation**: Can be run manually with `npm run generate-apps-metadata` in the `frontend/packages/ui` directory

- **Future Enhancement**: Server owners can hide apps from the store that they've deactivated, while still keeping the metadata in the build for potential re-activation

## Most Used Apps

The "Most used" section displays the most popular apps based on usage in the last 30 days across all users.

### How It Works

1. **Data Source**: Queries the `app_analytics` collection filtered by `timestamp >= (now - 30 days)`
2. **Aggregation**: Groups by `app_id` and counts total usage
3. **Caching**: Results are cached for 1 hour to reduce database load
4. **Public Endpoint**: `GET /api/apps/most-used` (no authentication required, rate limited to 30 requests/minute)

### Privacy

- Only aggregate app-level counts (no user-specific data)
- 30-day rolling window ensures relevance
- No personal information exposed
- Data comes from anonymous `app_analytics` collection (completely separate from user-specific `usage` collection)

### Implementation Details

- **Backend**: `backend/core/api/app/routes/apps.py:get_most_used_apps()`
- **Analytics Collection**: `backend/core/directus/schemas/app_analytics.yml`
- **Cache**: 1-hour TTL via `CacheService.get_most_used_apps_cached()`
- **Frontend Store**: `frontend/packages/ui/src/stores/mostUsedAppsStore.ts`
- **Frontend Fetch**: Triggered on app load in `frontend/apps/web_app/src/routes/+page.svelte` to ensure data is available when App Store opens
- **Frontend Component**: `SettingsAppStore.svelte` reads from the global store

## Top Picks for You - Personalization

The "Top picks for you" category provides personalized app recommendations based on conversation context and usage patterns.

### How It Works

1. **Post-Processing Generation**: After each AI response, the post-processing LLM analyzes the conversation and generates up to 5 recommended app IDs that would be most useful for the user based on the current context.

2. **Client-Side Aggregation**: The client aggregates recommendations from the last 20 chats:
   - Each chat stores its recommended apps (encrypted with chat-specific key)
   - The client decrypts and counts app mentions across recent chats
   - The top 5 most frequently recommended apps are selected

3. **User Profile Storage**: The aggregated top 5 apps are stored in the user profile:
   - Stored encrypted in IndexedDB (decrypted on-demand for display)
   - Synced to Directus for cross-device access (encrypted with user's master key)
   - Updated incrementally after each post-processing completion

4. **Display Logic**:
   - **Authenticated users with recommendations**: Shows personalized top 5 apps
   - **New users or no recommendations**: Falls back to random apps
   - **Unauthenticated users**: Always shows random apps

### Privacy & Zero-Knowledge Architecture

- **Server never sees aggregated recommendations**: All aggregation happens client-side
- **Encrypted storage**: Recommendations are encrypted at rest (chat-specific key for per-chat data, master key for user profile)
- **No tracking**: App Store browsing itself is not tracked
- **Client-controlled**: User's device performs all recommendation logic

### Implementation Details

- **Backend**: Post-processing tool includes `top_recommended_apps_for_user` field (array of up to 5 app IDs)
- **Frontend**: Client aggregates from `encrypted_top_recommended_apps_for_chat` fields in recent chats
- **Storage**: User profile includes `encrypted_top_recommended_apps` field for persistent storage
- **Update Frequency**: Recommendations update after each post-processing completion (incremental updates)

## Privacy Considerations

The App Store is designed with privacy in mind:

- **No Tracking**: App Store browsing is not tracked or logged
- **Transparent Pricing**: All skill costs are clearly displayed before use
- **Provider Transparency**: Users can see which external services are used
- **No Personal Data**: App Store interactions don't send personal data to external services
- **Zero-Knowledge Recommendations**: Top picks aggregation happens entirely client-side, server never sees the aggregated results
- **Anonymous Analytics**: Most used apps data comes from completely anonymous analytics (no user linkage, no encryption needed)
- **Encrypted Usage Data**: User-specific usage entries encrypt app_id, skill_id, and model_used to protect privacy from server admins

## Related Documentation

- [Apps Architecture](./README.md) - Overview of apps, skills, and focus modes
- [App Skills Architecture](./skills.md) - Detailed skill implementation
- [Focus Modes](./focus-modes.md) - How focus modes work
- [REST API Architecture](../architecture/rest-api.md) - Developer API for apps
- [App Settings and Memories](./settings-and-memories.md) - App-specific user data
