/**
 * Task inventory completeness contract for the installed CLI's shared client.
 * Tests transport requests with more than the backend default 100 records.
 * No CLI source entrypoint, credentials or real account are executed here.
 * Saturated server pages must fail instead of claiming exhaustive discovery.
 * Existing account/team context and blind Codex filters remain unchanged.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.js";

test("Task discovery requests 500 and preserves Codex/account scope", async () => {
  const client = Object.create(OpenMatesClient.prototype);
  client.requireSession = () => ({});
  client.resolveTeamContext = (context) => { assert.equal(context.teamId, "team"); return "team"; };
  client.getCliRequestHeaders = () => ({ unchanged: "auth" });
  client.http = { get: async (url, headers) => {
    assert.ok(url.includes("limit=500"));
    assert.ok(url.includes("external_chat_provider=codex"));
    assert.ok(url.includes("external_chat_lookup_hash=" + "a".repeat(64)));
    assert.ok(url.includes("team_id=team"));
    assert.deepEqual(headers, { unchanged: "auth" });
    return { ok: true, data: { tasks: Array.from({length:185}, (_,i) => ({task_id:String(i)})) } };
  }};
  assert.equal((await client.listUserTasks({teamId:"team", externalChatProvider:"codex", externalChatLookupHash:"a".repeat(64)})).length,185);
  client.http.get = async () => ({ok:true,data:{tasks:Array.from({length:500},(_,i)=>({task_id:String(i)}))}});
  await assert.rejects(client.listUserTasks({teamId:"team"}), /TASK_LIST_INCOMPLETE/);
});
