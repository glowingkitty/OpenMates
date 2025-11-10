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
  - **Top picks for you**: Personalized recommendations based on usage
  - **New apps**: Recently added apps
  - **For work**: Productivity and professional tools (e.g., Code, Email)
  - **For everyday life**: General purpose apps (e.g., Videos, Calendar)
  - Additional categories may be added as the app ecosystem grows
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

- **Dynamic Discovery**: Apps are automatically discovered from the backend, so new apps appear in the store without manual updates

## Privacy Considerations

The App Store is designed with privacy in mind:

- **No Tracking**: App Store browsing is not tracked or logged
- **Transparent Pricing**: All skill costs are clearly displayed before use
- **Provider Transparency**: Users can see which external services are used
- **No Personal Data**: App Store interactions don't send personal data to external services

## Related Documentation

- [Apps Architecture](./README.md) - Overview of apps, skills, and focus modes
- [App Skills Architecture](./app_skills.md) - Detailed skill implementation
- [Focus Modes](./focus_modes.md) - How focus modes work
- [REST API Architecture](../rest_api.md) - Developer API for apps
- [App Settings and Memories](./app_settings_and_memories.md) - App-specific user data
