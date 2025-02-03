// place files you want to import through the `$lib` alias in this folder.
export { default as ActiveChat } from "./src/components/ActiveChat.svelte";
export { default as Header } from "./src/components/Header.svelte";
export { default as Footer } from "./src/components/Footer.svelte";
export { default as Settings } from "./src/components/Settings.svelte";
export { default as ActivityHistory } from "./src/components/activity_history/ActivityHistory.svelte";
// i18n exports
export * from "./src/i18n/setup";
export * from "./src/i18n/types";

// Styles
export * from "./src/styles/constants";

// Actions
export { replaceOpenMates } from "./src/actions/replaceText";

// Config
export * from "./src/config/links";
