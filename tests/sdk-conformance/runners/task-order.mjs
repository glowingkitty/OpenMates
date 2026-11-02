// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const { sortTasks, SessionClientError } = await import("../../../frontend/packages/openmates-cli/dist/sdk-entry.js");
const capability="local.task-order.v1", args=process.argv.slice(2),option=name=>args[args.indexOf(name)+1];
assert.equal(option("--capability"),capability);
const raw=readFileSync(option("--fixture")),suite=JSON.parse(raw).capabilities[capability];
assert.ok(suite.vectors.length>0);
const results=[];
for(const vector of suite.vectors) {
  const rows=vector.tasks, before=structuredClone(rows);
  if(vector.error) {
    assert.throws(()=>sortTasks(rows,{locale:vector.locale}),error=>error instanceof SessionClientError && error.code===vector.error);
  } else {
    const ordered=sortTasks(rows,{locale:vector.locale});
    assert.notEqual(ordered,rows);
    assert.equal(ordered.length,vector.expected_indices.length);
    ordered.forEach((row,index)=>assert.equal(row,rows[vector.expected_indices[index]],vector.id));
    assert.deepEqual(ordered,vector.expected_indices.map(index=>before[index]));
  }
  assert.deepEqual(rows,before,"input rows remain unchanged on success or error");
  results.push({id:vector.id,status:"passed"});
}
console.log(JSON.stringify({capability,language:"npm",status:"passed",fixtureSha256:createHash("sha256").update(raw).digest("hex"),results}));
