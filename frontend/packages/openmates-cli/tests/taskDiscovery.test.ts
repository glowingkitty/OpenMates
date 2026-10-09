/**
 * Task inventory completeness contract for the installed CLI's shared client.
 * Tests transport requests with backend cursor paging.
 * No CLI source entrypoint, credentials or real account are executed here.
 * Legacy saturated server pages must fail instead of claiming exhaustive discovery.
 * Existing account/team context and blind Codex filters remain unchanged.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.js";

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,tasks.external-chat.encrypted-context
test("Task discovery requests paginated 100 and preserves Codex/account scope", async () => {
  const client = Object.create(OpenMatesClient.prototype);
  client.session = { apiUrl: 'http://localhost', hashedEmail: 'synthetic', sessionId: 'synthetic',
    createdAt: 1, masterKeyExportedB64: 'synthetic', activeTeamId: 'team' };
  client.requireSession = () => client.session;
  client.resolveTeamContext = (context) => { assert.equal(context.teamId, "team"); return "team"; };
  client.getCliRequestHeaders = () => ({ unchanged: "auth" });
  client.http = { get: async (url, headers) => {
    assert.ok(url.includes("limit=100"));
    assert.ok(url.includes("paginate=true"));
    assert.ok(url.includes("external_chat_provider=codex"));
    assert.ok(url.includes("external_chat_lookup_hash=" + "a".repeat(64)));
    assert.ok(url.includes("team_id=team"));
    assert.deepEqual(headers, { unchanged: "auth" });
    return { ok: true, data: { tasks: Array.from({length:85}, (_,i) => ({task_id:String(i).padStart(3, '0')})),
      complete: true, next_cursor: null } };
  }};
  assert.equal((await client.listUserTasks({teamId:"team", externalChatProvider:"codex", externalChatLookupHash:"a".repeat(64)})).length,85);
  client.http.get = async () => ({ok:true,data:{tasks:Array.from({length:100},(_,i)=>({task_id:String(i).padStart(3, '0')}))}});
  await assert.rejects(client.listUserTasks({teamId:"team"}), /TASK_LIST_INCOMPLETE/);
});
