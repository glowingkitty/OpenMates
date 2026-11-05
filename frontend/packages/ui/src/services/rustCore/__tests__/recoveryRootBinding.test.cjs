// contract-test-file: tooling
// Actual adapter code +explicit fixture-only native event realm. No product IO.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {api,fixture,Factory}=require('./helpers/nativeRustChatIOSetup.cjs');
test('native recovery IO root requires SAME original issuer Worker and factory; structural combinations refuse',async()=>{
 const a=await fixture(),b=await fixture(),root=a.root();
 api.assertRustChatIORootFactory(root,a.factory);
 api.assertNativeRustChatIORootBinding(root,a.issuer,a.worker,a.factory);
 assert.throws(()=>api.assertRustChatIORootFactory(root,new Factory()),/invalidated_snapshot/);
 assert.throws(()=>api.assertRustChatIORootFactory({...root},a.factory),/invalidated_snapshot/);
 for(const [issuer,worker,factory] of [[b.issuer,a.worker,a.factory],[a.issuer,b.worker,a.factory],[a.issuer,a.worker,b.factory]])
  assert.throws(()=>api.assertNativeRustChatIORootBinding(root,issuer,worker,factory),/invalidated_snapshot/);
 await a.host.closeAndDrain();await b.host.closeAndDrain();
 assert.throws(()=>api.assertRustChatIORootFactory(root,a.factory),/invalidated_snapshot/);
});
test('original root callback returning normally cannot hide synchronous root or issuer revocation',async()=>{
 for(const revoke of ['root','issuer']){
  const f=await fixture();let armed=false,root;
  root=f.host.openChatIORoot(f.factory,()=>{if(armed){if(revoke==='root')api.revokeRustChatIORoot(root);else api.revokeNativeRustChatIOFactory(f.issuer,f.worker);}});
  armed=true;
  assert.throws(()=>api.assertNativeRustChatIORootBinding(root,f.issuer,f.worker,f.factory),/invalidated_snapshot/);
  assert.throws(()=>api.assertRustChatIORootFactory(root,f.factory),/invalidated_snapshot/);
  await f.host.closeAndDrain();
 }
});
