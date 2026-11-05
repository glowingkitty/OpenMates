/** SDK-only authenticated format fallback; never changes the legacy CLI. */
// contract-test-file: tooling
import assert from "node:assert/strict";
import { createCipheriv } from "node:crypto";
import { test } from "node:test";
import { decryptBytesWithAesGcm, decryptWithAesGcmCombined, sdkKeyFingerprint } from "../src/sdkCrypto.ts";

function seal(key: Uint8Array, iv: Uint8Array, data: Uint8Array, aad?: string): Buffer {
  const aes=createCipheriv("aes-256-gcm",key,iv);
  if(aad) aes.setAAD(Buffer.from(aad));
  return Buffer.concat([Buffer.from(iv),aes.update(data),aes.final(),aes.getAuthTag()]);
}
test("legacy OM IV collisions preserve binary data and authenticate optional AAD",async()=>{
 const key=new Uint8Array(32).fill(7),aad="synthetic:expected-context";
 for(const marker of [Uint8Array.of(0xde,0xad,0xbe,0xef),sdkKeyFingerprint(key),Uint8Array.of(1,0,0,0)]){
  const iv=Buffer.concat([Buffer.from("OM"),marker,Buffer.from([6,7,8,9,10,11])]);
  const binary=Uint8Array.from({length:256},(_,i)=>i);
  assert.deepEqual(await decryptBytesWithAesGcm(seal(key,iv,binary).toString("base64"),key),binary);
  const text="Synthetic AAD payload ✓",raw=seal(key,iv,Buffer.from(text),aad);
  for(const combined of [raw,Buffer.concat([Buffer.from("OM"),sdkKeyFingerprint(key),raw])]){
   const encoded=combined.toString("base64");
   assert.equal(await decryptWithAesGcmCombined(encoded,key,aad),text);
   assert.equal(await decryptWithAesGcmCombined(encoded,key,"wrong-context"),null);
   assert.equal(await decryptWithAesGcmCombined(encoded,key),null);
   const tag=Buffer.from(combined);tag[tag.length-1]^=1;
   assert.equal(await decryptWithAesGcmCombined(tag.toString("base64"),key,aad),null);
  }
 }
});
test("apparent fingerprints and short buffers never replace GCM authentication",async()=>{
 const key=new Uint8Array(32).fill(7);
 for(const marker of [sdkKeyFingerprint(key),Uint8Array.of(1,0,0,0),Uint8Array.of(0xde,0xad,0xbe,0xef)]){
  const encoded=Buffer.concat([Buffer.from("OM"),marker,Buffer.alloc(28)]).toString("base64");
  assert.equal(await decryptBytesWithAesGcm(encoded,key),null);
  assert.equal(await decryptWithAesGcmCombined(encoded,key),null);
 }
 for(let size=0;size<28;size++)assert.equal(await decryptBytesWithAesGcm(Buffer.alloc(size).toString("base64"),key),null);
 assert.equal(await decryptBytesWithAesGcm(Buffer.alloc(34).toString("base64"),new Uint8Array(31)),null);
});
