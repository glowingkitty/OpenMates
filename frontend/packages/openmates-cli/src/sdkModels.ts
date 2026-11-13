/**
 * API-key SDK decrypted presentation models over the shared Rust core (portable WASM).
 *
 * Mirrors Rust `openmates_sdk::model` and Python `openmates.models`: the Rust serde
 * layout fills defaults and refuses missing required fields (`invalid_argument`).
 * StreamUpdate and Mutation are not exposed yet. Vectors:
 * tests/sdk-conformance/fixtures/sdk-models.json.
 */
import { callSdkWasm } from "./sdkWasmCall.js";

export interface ModelItem { id: string; title: string; description: string; status: string; category: string; fields: unknown }
export interface ModelMessage { id: string; role: string; content: string; sender: string; thinking: string; embeds: ModelItem[] }
export interface ModelChat { id: string; title: string; category: string; messages: ModelMessage[] }
export interface ModelWorkspace { id: "chats" | "apps" | "projects" | "workflows" | "tasks" | "settings"; label: string }

/** Canonical model parsing; every value is validated by the shared Rust layout. */
export const models = Object.freeze({
  /** Parse a decrypted chat (with nested messages/embeds) into its canonical layout. */
  parseChat(value: Record<string, unknown>): ModelChat {
    return callSdkWasm<ModelChat>("models", { kind: "chat", value });
  },
  /** Parse a decrypted message into its canonical layout. */
  parseMessage(value: Record<string, unknown>): ModelMessage {
    return callSdkWasm<ModelMessage>("models", { kind: "message", value });
  },
  /** Parse a workspace item into its canonical layout. */
  parseItem(value: Record<string, unknown>): ModelItem {
    return callSdkWasm<ModelItem>("models", { kind: "item", value });
  },
  /** Workspaces in display order with their labels. */
  workspaces(): ModelWorkspace[] {
    return callSdkWasm<ModelWorkspace[]>("models", { kind: "workspaces" });
  },
});
