// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import { test } from "node:test";
import assert from "node:assert/strict";
import { sortTasks } from "../src/sdkTaskOrder.ts";
import { SessionClientError } from "../src/sdkSession.ts";

test("stateless sorting preserves caller references and opaque metadata", () => {
  const metadata: Record<string,unknown> = { privateValue:1n }; metadata.self=metadata;
  const b={title:"b",position:0,metadata}, a={title:"a",position:null,metadata};
  const input=[b,a,a], output=sortTasks(input,{locale:"en"});
  assert.notEqual(output,input);
  assert.deepEqual(output,[a,a,b]);
  assert.equal(output[0],a); assert.equal(output[1],a);assert.equal(output[2],b);
  assert.equal(output[0].metadata,metadata);assert.deepEqual(input,[b,a,a]);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("non-JSON sort fields and unknown options fail without coercion", () => {
  const invalid = (operation:()=>unknown) => assert.throws(operation,error=>error instanceof SessionClientError && error.code==="invalid_argument");
  for(const position of [NaN,Infinity,-Infinity,"0",false,undefined]) invalid(()=>sortTasks([{position}] as never,{locale:"en"}));
  for(const row of [null,[],3,{title:3},{source:false}]) invalid(()=>sortTasks([row] as never,{locale:"en"}));
  invalid(()=>sortTasks([],{locale:"en",unknown:true} as never));
  invalid(()=>sortTasks([],{locale:3} as never));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("malformed locale tags are rejected by the shared SDK", () => {
  for (const locale of ["", "en_US", "en-@-invalid"]) {
    assert.throws(()=>sortTasks([],{locale}),error=>error instanceof SessionClientError && error.code==="invalid_argument");
  }
});
