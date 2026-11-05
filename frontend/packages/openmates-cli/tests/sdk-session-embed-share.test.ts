/** Facade boundary only; native admission/crypto is exercised by conformance. */
// contract-test-file: tooling
import {test} from "node:test";
import assert from "node:assert/strict";
import {SessionClient,SessionClientError,SessionEmbeds} from "../src/sdkSession.ts";
function facade(native:unknown){const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,"native",{value:native});Object.defineProperty(client,"essentialEpoch",{value:0,writable:true});return {client,embeds:new SessionEmbeds(native as never,operation=>Reflect.get(client,"essentialInvoke").call(client,operation))};}
test("share forwards signed i64 exactly and arbitrary SDK password without key DTO",async()=>{
 const calls:unknown[]=[];const {embeds}=facade({embedsShareUrl:async(...args:unknown[])=>{calls.push(args);return "https://app.example.org/share/embed/id#key=synthetic";}});
 for(const expires of [0,-7,9223372036854775807n,-9223372036854775808n])assert.match(await embeds.shareUrl("full-id",expires,"synthetic-long-password"),/#key=/);
 assert.deepEqual(calls.map(x=>(x as string[])[1]),["0","-7","9223372036854775807","-9223372036854775808"]);
 for(const value of [true,1.5,NaN,Infinity,9007199254740992,9223372036854775808n])await assert.rejects(()=>embeds.shareUrl("full-id",value as never),e=>e instanceof SessionClientError&&e.code==="invalid_argument");
 assert.equal(calls.length,4);
});
test("late cancel suppresses secret URL and failures never echo native secrets",async()=>{
 let complete:(s:string)=>void=()=>assert.fail("not started");const {client,embeds}=facade({embedsShareUrl:()=>new Promise<string>(r=>{complete=r;}),cancel:()=>{}});
 const pending=embeds.shareUrl("full-id");client.cancel();complete("https://app.example.org/#key=synthetic-secret");await assert.rejects(()=>pending,e=>e instanceof SessionClientError&&e.code==="cancelled"&&!e.message.includes("synthetic-secret"));
 const bad=facade({embedsShareUrl:()=>{throw Error("synthetic-private-key-password");}});await assert.rejects(()=>bad.embeds.shareUrl("full-id"),e=>e instanceof SessionClientError&&e.code==="native_failure"&&!e.message.includes("synthetic"));
});
