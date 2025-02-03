// place files you want to import through the `$lib` alias in this folder.
export { default as ActiveChat } from "../routes/components/ActiveChat.svelte";
export { default as Header } from "../routes/components/Header.svelte";
export { default as Footer } from "../routes/components/Footer.svelte";
export { default as Settings } from "../routes/components/Settings.svelte";
export { default as ActivityHistory } from "../routes/components/activity_history/ActivityHistory.svelte";

// Expose stores for a unified public API
export { isMenuOpen } from "./stores/menuState"; // Adjust path if needed
export { isAuthenticated } from "./stores/authState";
export { settingsMenuVisible, isMobileView } from "../routes/components/Settings.svelte";
