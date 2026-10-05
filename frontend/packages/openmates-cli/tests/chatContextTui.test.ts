/** Inspectable TUI receipts and click-triggered background authoring controls. */
// contract-test-file: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction,focus-modes.project-authoring-click
import { it } from "node:test";
import assert from "node:assert/strict";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.ts";
import { handleWorkspaceCommand } from "../src/tuiWorkspaceController.ts";
import { DIRECTION_CORRECTION_NOTICE } from "../src/chatContextEvents.ts";

function stateWithReceipts() {
  const state = createInitialTuiState();
  state.screen = "chat"; state.workspace = "chats"; state.activeChatId = "chat";
  state.messages = [
    { role: "user", content: "Improve Project guidance." },
    { role: "system", content: JSON.stringify({ type: "rules_loaded", event_id: "rules", created_at: 1, count: 1,
      set_key: "rules-v1", rules: [{ id: "python", title: "Python", source: "app", revision: "v1", body: "Full guide body for inspection." }] }) },
    { role: "system", content: JSON.stringify({ type: "chat_direction_correction", event_id: "correction", created_at: 2,
      notice: DIRECTION_CORRECTION_NOTICE, instruction: "Full correction instruction for inspection.", delivery_id: "delivered" }) },
    { role: "system", content: JSON.stringify({ type: "project_authoring_recommendation", event_id: "recommendation", created_at: 3,
      chat_id: "chat", recommendation_id: "token", project_id: "project", action: "create", kind: "focus" }) },
  ];
  return state;
}

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction,focus-modes.project-authoring-click
it("renders quiet summaries and reveals complete applied Rule/correction details only on inspection", async () => {
  const state = stateWithReceipts();
  const frame = renderTuiFrame(state, 120, 50, { colorMode: "none" });
  assert.match(frame, /Loaded 1 rules/); assert.match(frame, /Correction instruction was sent/);
  assert.doesNotMatch(frame, /Full guide body|Full correction instruction/);
  assert.match(frame, /Create Focus/); assert.match(frame, /focus-author 3/);
  const context = { state, client: {} as never, terminal: {} as never, render() {}, async command() {}, async send() {} };
  await handleWorkspaceCommand(context, "/context 1");
  assert.match(state.detailLines.join("\n"), /Full guide body for inspection/);
  await handleWorkspaceCommand(context, "/context 2");
  assert.match(state.detailLines.join("\n"), /Full correction instruction for inspection/);
});

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction,focus-modes.project-authoring-click
it("starts one idempotent background job only from an explicit control and keeps the same chat", async () => {
  const state = stateWithReceipts();
  let calls = 0;
  let release: ((value: Record<string, unknown>) => void) | undefined;
  const pending = new Promise<Record<string, unknown>>(resolve => { release = resolve; });
  const context = { state, client: {
    async getActiveProjectFocus() { return { project_id: "project", team_id: null }; },
    async startProjectAuthoringJob(_projectId: string, input: Record<string, unknown>) {
      calls++; assert.equal(input.recommendation_id, "token"); return pending;
    },
  } as never, terminal: {} as never, render() {}, async command() {}, async send() { throw new Error("must not create an authoring chat"); } };
  assert.equal(calls, 0);
  const first = handleWorkspaceCommand(context, "/focus-author 3");
  await handleWorkspaceCommand(context, "/focus-author 3");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  release?.({ job_id: "job", status: "running" }); await first;
  assert.equal(state.activeChatId, "chat"); assert.equal(state.isBusy, false);
  assert.equal(state.chatContextAuthoringJobs.recommendation.jobId, "job");
  assert.equal(state.chatContextAuthoringJobs.recommendation.status, "running");
});
