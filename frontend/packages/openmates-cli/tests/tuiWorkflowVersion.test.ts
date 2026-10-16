/** Historical workflow graph API envelope; synthetic transport, no account state. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.js";

// contract-test: supporting surface=cli assertions=workflows.surface.semantic-parity
test("historical workflow graph uses the version endpoint response envelope", async () => {
  const graph = {version:1,trigger_node_id:null,nodes:[],edges:[]};
  let requested = "";
  const client = Object.assign(Object.create(OpenMatesClient.prototype), {
    requireSession() {}, getCliRequestHeaders: () => ({}), appendTeamQuery: (url:string) => url,
    http: {get: async (url:string) => {requested=url;return {ok:true,status:200,data:{version:{id:"v-old",graph}}};}},
  }) as OpenMatesClient;
  assert.deepEqual(await client.getWorkflowVersion("wf-one","v-old"),{graph});
  assert.equal(requested,"/v1/workflows/wf-one/versions/v-old");
  Object.assign(client, {http:{get:async()=>({ok:true,status:200,data:{version:{id:"v-old"}}})}});
  await assert.rejects(client.getWorkflowVersion("wf-one","v-old"), /Workflow version failed/);
});
