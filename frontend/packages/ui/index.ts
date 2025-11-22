// Components
export { default as HeroHeader } from "./src/components/HeroHeader.svelte";
export { default as ActiveChat } from "./src/components/ActiveChat.svelte";
export { default as Notification } from "./src/components/Notification.svelte";
export { default as DemoChat } from "./src/components/DemoChat.svelte";
export { default as Header } from "./src/components/Header.svelte";
export { default as Footer } from "./src/components/Footer.svelte";
export { default as Settings } from "./src/components/Settings.svelte";
export { default as Login } from "./src/components/Login.svelte";
export { default as Chats } from "./src/components/chats/Chats.svelte";
export { default as MetaTags } from "./src/components/MetaTags.svelte";
export { default as Icon } from "./src/components/Icon.svelte";
export { default as AnimatedChatExamples } from "./src/components/AnimatedChatExamples.svelte";
export { default as WaitingList } from "./src/components/WaitingList.svelte";
export { default as Highlights } from "./src/components/Highlights.svelte";
export { default as DesignGuidelines } from "./src/components/DesignGuidelines.svelte";
export { default as Community } from "./src/components/Community.svelte";
export { default as AppIconGrid } from "./src/components/AppIconGrid.svelte";
export { default as LargeSeparator } from "./src/components/LargeSeparator.svelte";
export { default as APIexample } from "./src/components/APIexample.svelte";
export { default as ProcessingDetails } from "./src/components/ProcessingDetails.svelte";
export { default as ChatMessage } from "./src/components/ChatMessage.svelte";
export { default as Field } from "./src/components/Field.svelte";
export { default as Button } from "./src/components/Button.svelte";
export { default as HealthAppCard } from "./src/components/cards/HealthAppCard.svelte";
export { default as EventAppCard } from "./src/components/cards/EventAppCard.svelte";
// Removed Imprint, Privacy, Terms Svelte components - legal documents are now handled via chat system
// See frontend/packages/ui/src/legal/ for legal chat document definitions
// Removed export * from Settings.svelte as default export on line 6 is sufficient
// Types
export * from "./src/types/chat";

// i18n exports
export * from "./src/i18n/setup";
export * from "./src/i18n/types";
export * from "./src/i18n/translations";
export { SUPPORTED_LANGUAGES, LANGUAGE_CODES, SUPPORTED_LOCALES, getLanguageByCode, isLanguageSupported } from "./src/i18n/languages";

// Stores
export * from "./src/stores/theme";
export * from "./src/stores/authStore"; // Export everything from authStore
export * from "./src/stores/menuState";
export * from "./src/stores/signupState";
export * from "./src/stores/panelStateStore"; // Export the new panel state store
export * from "./src/stores/uiStateStore"; // Also export the ui state store
export * from "./src/stores/settingsDeepLinkStore"; // Export the settings deep link store
export * from "./src/stores/activeChatStore"; // Export the active chat store for URL-based navigation
export * from "./src/stores/phasedSyncStateStore"; // Export the phased sync state store
export * from "./src/stores/websocketStatusStore"; // Export the WebSocket status store
export * from "./src/stores/userProfile"; // Export the user profile store for accessing last_opened chat
export * from "./src/stores/i18n"; // Export i18n stores (i18nLoaded, waitForTranslations)
export * from "./src/stores/notificationStore"; // Export notification store for displaying notifications
export * from "./src/stores/mostUsedAppsStore"; // Export most used apps store for App Store
// loginOverlayStore removed - not needed

// Demo Chats
export * from "./src/demo_chats/store"; // Export demo chat stores
export * from "./src/demo_chats"; // Export demo chat data and helpers

// Services
export { chatDB } from "./src/services/db"; // Export chat database
export { chatSyncService } from "./src/services/chatSyncService"; // Export chat sync service
export { webSocketService } from "./src/services/websocketService"; // Export WebSocket service for auth error handling
export * from "./src/services/chatUrlService"; // Export chat URL service for deep linking
export { getKeyFromStorage, checkAndClearMasterKeyOnLoad } from "./src/services/cryptoService"; // Export getKeyFromStorage and checkAndClearMasterKeyOnLoad for offline-first auth

// Styles
export * from "./src/styles/constants";
import "./src/styles/buttons.css";
import "./src/styles/fields.css";
import "./src/styles/cards.css";
import "./src/styles/chat.css";
import "./src/styles/mates.css";
import "./src/styles/theme.css";
import "./src/styles/fonts.css";
import "./src/styles/icons.css";

// Actions
export { tooltip } from "./src/actions/tooltip";

// Config
export * from "./src/config/links";
export * from "./src/config/meta";