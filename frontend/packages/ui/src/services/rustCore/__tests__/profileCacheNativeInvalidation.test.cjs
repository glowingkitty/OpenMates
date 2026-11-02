// contract-test-file: tooling
// Actual adapter/Host with explicit native-event fixtures only, no browser proof.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {api,fixture,connection,FixtureNativeEvent}=require('./helpers/nativeRustChatIOSetup.cjs');
for(const kind of ['versionchange','close'])test('original native '+kind+' clears an idle rendered child without another action',async()=>{
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),db=connection(f,lease);
 let rendered='private selected plaintext',notifications=0;f.host.subscribeProfileCacheInvalidation(f.status,()=>{rendered=null;notifications++;});
 db.native(kind);assert.equal(rendered,null);assert.equal(notifications,1);assert.equal(f.host.closed,false);
 assert.throws(()=>f.host.assertProfileCacheCurrent(f.status));assert.throws(()=>api.assertRustChatIORootResource(root));
 db.native(kind);assert.equal(notifications,1);await f.host.closeAndDrain();
});
test('synthetic or foreign connection negatives cannot revoke the original Root',async()=>{
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),db=connection(f,lease);let notifications=0;
 f.host.subscribeProfileCacheInvalidation(f.status,()=>notifications++);
 db.dispatchEvent(new Event('versionchange'));db.dispatchEvent(new Event('close'));
 db.native('close',undefined,{});assert.equal(notifications,0);f.host.assertProfileCacheCurrent(f.status);
 db.native('close');assert.equal(notifications,1);await f.host.closeAndDrain();
});
test('original legacy connection close invalidates bound Root and observer failures cannot retain another child',async()=>{
 const f=await fixture(),root=f.root();api.openRustChatIORoutingLease(root,f.gate);let notifications=0;
 api.observeRustChatIORootInvalidation(root,()=>{throw Error('observer failure');});
 f.host.subscribeProfileCacheInvalidation(f.status,()=>notifications++);assert.throws(()=>api.observeRustChatIORootInvalidation({},()=>{}));
 f.legacy.native('close');assert.equal(notifications,1);assert.throws(()=>f.host.assertProfileCacheCurrent(f.status));
 let late=0;api.observeRustChatIORootInvalidation(root,()=>late++);assert.equal(late,1);await f.host.closeAndDrain();
});
