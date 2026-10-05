/** Phase restoration/history integration using the real SDK and a bounded mock transport. */
// contract-test-file: supporting surface=cli assertions=focus-modes.phases,focus-modes.restoration,focus-modes.history-events
import { after, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocketServer } from "ws";
const previousStateDir = process.env.OPENMATES_STATE_DIR;
const previousApiUrl = process.env.OPENMATES_API_URL;
const stateDir = mkdtempSync(join(tmpdir(), "openmates-focus-phases-"));
process.env.OPENMATES_STATE_DIR = stateDir;
delete process.env.OPENMATES_API_URL;
const { OpenMatesClient } = await import("../src/client.ts");
const { encryptBytesWithAesGcm, encryptWithAesGcmCombined, decryptWithAesGcmCombined,
  sealChatCompletionRecoveryPayload } = await import("../src/crypto.ts");
function writeLegacySession(apiUrl: string): void {
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  writeFileSync(join(stateDir, "session.json"), JSON.stringify({
    apiUrl, sessionId: "test-session-id", wsToken: "test-ws-token",
    cookies: { auth_refresh_token: "test-refresh-token" },
    masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    emailEncryptionKeyB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    hashedEmail: "test-hashed-email", userEmailSalt: "test-email-salt",
    createdAt: 1710000000000, authorizerDeviceName: "Test Browser", autoLogoutMinutes: null,
  }), { mode: 0o600 });
}
after(() => {
  if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
  else process.env.OPENMATES_STATE_DIR = previousStateDir;
  if (previousApiUrl === undefined) delete process.env.OPENMATES_API_URL;
  else process.env.OPENMATES_API_URL = previousApiUrl;
  rmSync(stateDir, { recursive: true, force: true });
});
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  // contract-test: supporting surface=cli assertions=focus-modes.full-instruction,focus-modes.restoration
  const cases: Array<{ restoredFocus: string | null; claimOutcome: "leased" | "terminal-after-conflict" | "foreign-terminal" | "generic-error" | "foreign-conflict" }> = [
    { restoredFocus: "jobs-career_insights", claimOutcome: "leased" },
    { restoredFocus: null, claimOutcome: "leased" },
    { restoredFocus: "jobs-career_insights", claimOutcome: "terminal-after-conflict" },
    { restoredFocus: "jobs-career_insights", claimOutcome: "foreign-terminal" },
    { restoredFocus: "jobs-career_insights", claimOutcome: "generic-error" },
    { restoredFocus: "jobs-career_insights", claimOutcome: "foreign-conflict" },
  ];
  for (const { restoredFocus, claimOutcome } of cases) {
  // contract-test: supporting surface=cli assertions=focus-modes.phases,focus-modes.restoration,focus-modes.history-events,rules.transparency.applied-set,chats.direction.reviewed-correction,chats.direction.context-assessment
  it(`restores encrypted phase progress and persists live history for saved chats (${restoredFocus ?? "off"}, ${claimOutcome})`, async () => {
    const chatId = "11111111-1111-4111-8111-111111111111";
    const ownerId = "22222222-2222-4222-8222-222222222222";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const rawChatKey = new Uint8Array(32).fill(7);
    const projectFocusId = "project-55555555-5555-4555-8555-555555555555";
    const initialPhase = { schema_version: 1, chat_id: chatId, focus_id: "jobs-career_insights",
      revision: "definition-v1", run_id: "old-run", version: 2, phase_id: "explore", complete: false, transitions: [] };
    const projectPhase = { ...initialPhase, focus_id: projectFocusId, version: 4 };
    const savedPhases = restoredFocus ? { [restoredFocus]: initialPhase, [projectFocusId]: projectPhase } : {};
    const phaseEvent = { type: "focus_phase_changed", event_id: "66666666-6666-4666-8666-666666666666",
      chat_id: chatId, focus_id: "jobs-career_insights", run_id: "new-run", version: 1,
      previous_phase_id: "confirm_profile", phase_id: "explore", phase_title: "Explore career directions",
      direction: "forward", created_at: 1770000000 };
    const appliedRules = { type: "rules_loaded", event_id: "77777777-7777-4777-8777-777777777777", created_at: 1770000001,
      count: 1, set_key: "applied-rule-set", rules: [{ id: "guide", title: "Python practices", source: "app", revision: "v1", body: "Use bounded inputs." }] };
    const appliedCorrection = { type: "chat_direction_correction", event_id: "88888888-8888-4888-8888-888888888888", created_at: 1770000002,
      notice: "Chat is drifting too far away from the goals. Correction instruction was sent.", instruction: "Return to the actual goal while preserving Project grants.", delivery_id: "actual-delivery" };
    const livePhases = { "jobs-career_insights": { ...initialPhase, run_id: "new-run", version: 1, transitions: [phaseEvent] },
      [projectFocusId]: { ...projectPhase, version: 3 } };
    const planId = "99999999-9999-4999-8999-999999999999", planKey = new Uint8Array(32).fill(9);
    const approvedPlan = { plan_id: planId, status: "active", version: 4, primary_chat_id: chatId,
      approval_state: "approved", submitted_revision_id: "approved-plan-revision", approved_revision_id: "approved-plan-revision",
      encrypted_title: await encryptWithAesGcmCombined("Accepted repair Plan", planKey),
      encrypted_goal: await encryptWithAesGcmCombined("Fix the timeout while preserving access checks", planKey),
      encrypted_constraints: await encryptWithAesGcmCombined("Keep the repair within existing scope", planKey),
      key_wrappers: [{ key_type: "master", encrypted_plan_key: await encryptBytesWithAesGcm(planKey, new Uint8Array(32)) }] };
    const taskId = "99999999-9999-4999-8999-888888888888";
    const olderLinkedTask = { task_id: taskId, status: "blocked", version: 5, updated_at: 1, primary_chat_id: chatId,
      encrypted_task_key: await encryptBytesWithAesGcm(planKey, new Uint8Array(32)),
      encrypted_title: await encryptWithAesGcmCombined("Existing timeout repair", planKey),
      encrypted_description: await encryptWithAesGcmCombined("Return to the repair already linked to this chat", planKey) };
    const encryptedChatKey = await encryptBytesWithAesGcm(rawChatKey, new Uint8Array(32));
    writeFileSync(join(stateDir, "sync_cache.json"), JSON.stringify({
      syncedAt: Date.now(),
      totalChatCount: 1,
      loadedChatCount: 1,
      chats: [{
        details: { id: chatId, encrypted_chat_key: encryptedChatKey, messages_v: 7,
          encrypted_active_focus_id: restoredFocus ? await encryptWithAesGcmCombined(restoredFocus, rawChatKey) : null,
          encrypted_focus_phase_state: restoredFocus ? await encryptWithAesGcmCombined(JSON.stringify(savedPhases), rawChatKey) : null },
        messages: [],
      }],
      embeds: [],
      embedKeys: [],
    }));

    const captured: {
      preflightPayload?: Record<string, unknown>;
      messagePayload?: Record<string, unknown>;
      persistPayload?: Record<string, unknown>;
      focusUpdate?: Record<string, unknown>;
      phaseMetadata?: Record<string, unknown>;
      phaseMessages: Array<Record<string, unknown>>;
      frameTypes: string[];
    } = { frameTypes: [], phaseMessages: [] };
    let sealedPayloadForTest: string | null = null;
    let claimCount = 0;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
        return;
      }
      if (
        request.method === "GET" &&
        request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false"
      ) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url?.startsWith(`/v1/chats/${chatId}/messages/window`)) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ messages: [], has_more_before: false, start_cursor: null }));
        return;
      }
      if (request.method === "GET" && request.url?.startsWith("/v1/user-plans?chat_id=")) {
        response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ plans: [approvedPlan] })); return;
      }
      if (request.method === "GET" && request.url === `/v1/user-plans/${planId}`) {
        response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ plan: approvedPlan })); return;
      }
      if (request.method === "GET" && request.url?.startsWith("/v1/user-tasks?")) {
        response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ tasks: [olderLinkedTask,
          { ...olderLinkedTask, task_id: "older-unlinked", primary_chat_id: null }] })); return;
      }
      if (request.method === "GET" && request.url === `/v1/user-tasks/${taskId}/dependencies`) {
        response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ dependencies: [], blockers: [] })); return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        // Saved sends wait for the server's authoritative recovery discovery
        // handshake before dispatching; this fixture has no older outputs.
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "phased_sync_request") {
            ws.send(JSON.stringify({ type: "phase_2_last_20_chats_ready", payload: {
              total_chat_count: 1, chats: [{ chat_details: {
                id: chatId, encrypted_chat_key: encryptedChatKey, messages_v: 7,
                encrypted_active_focus_id: restoredFocus ? await encryptWithAesGcmCombined(restoredFocus, rawChatKey) : null,
                encrypted_focus_phase_state: captured.phaseMetadata?.encrypted_focus_phase_state
                  ?? (restoredFocus ? await encryptWithAesGcmCombined(JSON.stringify(savedPhases), rawChatKey) : null),
              }, messages: [] }],
            }}));
            ws.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          }
          if (frame.type === "chat_turn_preflight") {
            captured.preflightPayload = frame.payload;
            sealedPayloadForTest = JSON.stringify(await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantMessageId,
                category: null,
                chat_id: chatId,
                content: "ok",
                job_id: recoveryJobId,
                key_version: 1,
                model_name: null,
                turn_id: frame.payload.turn_id,
              })),
              {
                recoveryPublicKey: String(frame.payload.recovery_public_key),
                ownerId,
                chatId,
                turnId: String(frame.payload.turn_id),
                jobId: recoveryJobId,
                assistantMessageId,
                keyVersion: 1,
              },
            ));
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: { preflight_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", turn_id: frame.payload.turn_id },
            }));
          }
          if (frame.type === "update_encrypted_active_focus_id") captured.focusUpdate = frame.payload;
          if (frame.type === "encrypted_chat_metadata") {
            captured.phaseMetadata = frame.payload;
            ws.send(JSON.stringify({ type: "encrypted_metadata_stored", payload: { chat_id: chatId } }));
          }
          if (frame.type === "chat_system_message_added") captured.phaseMessages.push(frame.payload);
          if (frame.type === "chat_message_added") {
            ws.send(JSON.stringify({ type: "focus_mode_activated", payload: { chat_id: chatId, focus_id: "jobs-career_insights" } }));
            if (restoredFocus) ws.send(JSON.stringify({ type: "focus_phases_updated", payload: { chat_id: chatId, states: livePhases } }));
            captured.messagePayload = frame.payload;
            for (const event of [appliedRules, appliedRules, appliedCorrection, appliedCorrection]) ws.send(JSON.stringify({ type: "chat_context_applied", payload: { chat_id: chatId, event } }));
            ws.send(JSON.stringify({ type: "chat_context_applied", payload: { chat_id: "unrelated", event: { ...appliedRules, event_id: "unrelated-event" } } }));
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: { chat_id: chatId, message_id: message.message_id, new_messages_v: 9 },
            }));
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: chatId,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "ok",
                  is_final_chunk: true,
                },
              }));
              ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: chatId } }));
            }, 10);
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "recovery_jobs_available",
                payload: {
                  jobs: [{
                    job_id: recoveryJobId,
                    chat_id: chatId,
                    turn_id: captured.preflightPayload?.turn_id,
                    assistant_message_id: assistantMessageId,
                    chat_key_version: 1,
                  }],
                },
              }));
            }, 30);
          }
          if (frame.type === "recovery_job_claim") {
            claimCount += 1;
            if (claimOutcome === "generic-error" || claimOutcome === "foreign-conflict") {
              ws.send(JSON.stringify({ type: "error", payload: {
                code: claimOutcome === "generic-error" ? "recovery_job_expired" : "lease_conflict",
                message: "Encrypted completion recovery was rejected.",
                job_id: claimOutcome === "foreign-conflict" ? "other-job-id" : recoveryJobId,
                request_id: frame.payload.request_id,
              } }));
              if (claimOutcome === "foreign-conflict") {
                ws.send(JSON.stringify({ type: "error", payload: {
                  code: "recovery_job_expired", message: "Encrypted completion recovery was rejected.",
                  job_id: recoveryJobId, request_id: frame.payload.request_id,
                } }));
              }
              return;
            }
            if (claimOutcome !== "leased" && claimCount === 1) {
              ws.send(JSON.stringify({ type: "error", payload: {
                code: "lease_conflict", message: "Encrypted completion recovery was rejected.",
                job_id: recoveryJobId, request_id: frame.payload.request_id,
              } }));
              return;
            }
            assert.ok(sealedPayloadForTest);
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                request_id: frame.payload.request_id,
                state: claimOutcome === "leased" ? "LEASED" : "TERMINAL",
                lease_token: "lease-token-old-chat",
                lease_generation: 2,
                sealed_payload: sealedPayloadForTest,
                chat_id: claimOutcome === "foreign-terminal" ? "other-chat-id" : chatId,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "recovery_job_persist") {
            captured.persistPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "recovery_job_persisted",
              payload: { job_id: recoveryJobId, state: "TERMINAL", committed_messages_v: 9 },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      // This fixture tests request/recovery metadata; it has no phased-sync history server.
      if (claimOutcome === "foreign-terminal" || claimOutcome === "generic-error" || claimOutcome === "foreign-conflict") {
        await assert.rejects(
          client.sendMessage({ message: "Continue this old chat", chatId, messageHistory: [], jevContext: { custom_rule_documents: [{ id: "personal-guide", source: "personal", document: "---\nname: Personal practices\ndescription: Safe practices\n---\nKeep outputs bounded." }] } }),
          (error: Error) => {
            assert.match(error.message, claimOutcome === "foreign-terminal"
              ? /invalid lease or identity data/
              : /Encrypted completion recovery was rejected/);
            return true;
          },
        );
        assert.equal(claimCount, claimOutcome === "foreign-terminal" ? 2 : 1);
        assert.equal(captured.persistPayload, undefined);
        return;
      }
      const result = await client.sendMessage({ message: "Continue this old chat", chatId, messageHistory: [], jevContext: { custom_rule_documents: [{ id: "personal-guide", source: "personal", document: "---\nname: Personal practices\ndescription: Safe practices\n---\nKeep outputs bounded." }] } });
      assert.equal(result.status, "completed");
      assert.equal(claimCount, claimOutcome === "terminal-after-conflict" ? 2 : 1);

      assert.equal(captured.messagePayload?.active_focus_id, restoredFocus);
      assert.equal(captured.focusUpdate?.chat_id, chatId);
      assert.equal(await decryptWithAesGcmCombined(String(captured.focusUpdate?.encrypted_active_focus_id), rawChatKey), "jobs-career_insights");
      assert.ok(captured.preflightPayload);
      assert.equal(captured.preflightPayload.expected_messages_v, 7);
      assert.equal(captured.preflightPayload.encrypted_chat_key, encryptedChatKey);
      assert.equal(captured.preflightPayload.chat_key_version, 1);
      assert.equal(typeof captured.preflightPayload.recovery_public_key, "string");
      assert.equal(captured.preflightPayload.encrypted_chat_metadata, undefined);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), Boolean(restoredFocus));
      if (restoredFocus) {
        assert.deepEqual(captured.messagePayload?.focus_phase_state, savedPhases);
        const saved = JSON.parse(await decryptWithAesGcmCombined(String(captured.phaseMetadata?.encrypted_focus_phase_state), rawChatKey));
        assert.equal(saved[restoredFocus].run_id, "new-run");
        assert.equal(saved[restoredFocus].phase_id, "explore");
        assert.equal(saved[projectFocusId].version, 4, "Catalog activation retains newer Project phase progress");
        assert.equal(captured.phaseMessages.length, 3);
        const message = captured.phaseMessages.map(frame => frame.message as Record<string, unknown>).find(message => message.message_id === phaseEvent.event_id)!;
        assert.equal(message.role, "system");
        assert.equal(message.message_id, phaseEvent.event_id);
        assert.deepEqual(JSON.parse(await decryptWithAesGcmCombined(String(message.encrypted_content), rawChatKey)), phaseEvent);
      }
      assert.deepEqual(captured.messagePayload?.accepted_plan_context, { plan_id: planId, version: 4,
        approved_revision_id: "approved-plan-revision", summary: "Title: Accepted repair Plan\nGoal: Fix the timeout while preserving access checks\nConstraints: Keep the repair within existing scope" });
      assert.deepEqual(captured.messagePayload?.related_task_candidates, [{ task_id: taskId, title: "Existing timeout repair",
        summary: "Return to the repair already linked to this chat", project_id: null, status: "blocked", changed_at: 1,
        revision: "5", explicit_dependency: false }]);
      assert.deepEqual(captured.messagePayload?.custom_rule_documents, [{ id: "personal-guide", source: "personal", document: "---\nname: Personal practices\ndescription: Safe practices\n---\nKeep outputs bounded." }]);
      for (const expected of [appliedRules, appliedCorrection]) {
        const rows = captured.phaseMessages.map(frame => frame.message as Record<string, unknown>).filter(message => message.message_id === expected.event_id);
        assert.equal(rows.length, 1, "Actual context is persisted exactly once despite duplicate delivery");
        assert.deepEqual(JSON.parse(await decryptWithAesGcmCombined(String(rows[0].encrypted_content), rawChatKey)), expected);
      }
      assert.equal(captured.phaseMessages.some(frame => (frame.message as Record<string, unknown>).message_id === "unrelated-event"), false);
      assert.equal(captured.messagePayload?.protocol_version, 1);
      assert.equal(captured.messagePayload?.preflight_id, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
      assert.equal(captured.messagePayload?.turn_id, captured.preflightPayload.turn_id);
      assert.equal(captured.messagePayload?.recovery_public_key, captured.preflightPayload.recovery_public_key);
      assert.equal(captured.messagePayload?.chat_key_version, 1);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      if (claimOutcome === "leased") {
        assert.equal(captured.persistPayload?.expected_messages_v, 9);
        assert.equal(captured.persistPayload?.lease_token, "lease-token-old-chat");
        assert.equal(captured.persistPayload?.lease_generation, 2);
      } else {
        assert.equal(captured.persistPayload, undefined, "another device already persisted this completion");
      }
    } finally {
      rmSync(join(stateDir, "sync_cache.json"), { force: true });
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
  }
