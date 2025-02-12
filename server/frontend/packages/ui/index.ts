// Components
export { default as HeroHeader } from "./src/components/HeroHeader.svelte";
export { default as ActiveChat } from "./src/components/ActiveChat.svelte";
export { default as Header } from "./src/components/Header.svelte";
export { default as Footer } from "./src/components/Footer.svelte";
export { default as Settings } from "./src/components/Settings.svelte";
export { default as ActivityHistory } from "./src/components/activity_history/ActivityHistory.svelte";
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
export { default as Imprint } from "./src/components/Imprint.svelte";
export { default as Privacy } from "./src/components/Privacy.svelte";
export { default as Terms } from "./src/components/Terms.svelte";
export * from "./src/components/Settings.svelte";

// Types
export * from "./src/types/chat";

// i18n exports
export * from "./src/i18n/setup";
export * from "./src/i18n/types";

// Stores
export * from "./src/stores/theme";
export * from "./src/stores/authState";
export * from "./src/stores/menuState";
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
export { replaceOpenMates } from "./src/actions/replaceText";
export { tooltip } from "./src/actions/tooltip";

// Config
export * from "./src/config/links";
export * from "./src/config/meta";