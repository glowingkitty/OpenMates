// frontend/packages/ui/src/services/chatSyncUpdatesPolicy.ts
// Flag gate for the chat-update / recovery decision helpers. Default builds use
// the TypeScript helpers of chatSyncUpdatesLogic.ts unchanged; with
// VITE_OPENMATES_RUST_CORE=1 the handlers await the shared Rust Worker `sync`
// unit through rustCore/sync/rustChatUpdatesPolicy.ts (loaded lazily, never
// bundled into default builds). There is no TypeScript fallback with the flag on.
export { messagePreview, recoveredThinkingFields } from "./chatSyncUpdatesLogic";

// Measurement-only opt-out (`openmates_rust_core_sync` = 'ts'), read once per page load.
export const RUST_UPDATES_POLICY: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1"
  && !(typeof localStorage !== "undefined" && localStorage.getItem("openmates_rust_core_sync") === "ts");

export function rustUpdatesPolicy() {
  return import("./rustCore/sync/rustChatUpdatesPolicy");
}
