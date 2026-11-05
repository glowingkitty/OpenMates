// contract-test-file: tooling
// Actual native Root/lease/ports code; explicit native-event platform doubles.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {api,fixture}=require('./helpers/nativeRustChatIOSetup.cjs');
test('actual opaque ports require SAME original Root/factory and reject copied/cross-owner resources',async()=>{
 const a=await fixture(),b=await fixture(),root=a.root(),other=b.root();const ports=api.createRustChatIOPorts(api.openRustChatIORoutingLease(root,a.gate),a.factory);
 api.assertRustChatIOPortsRoot(ports,root,a.factory);assert.throws(()=>api.assertRustChatIOPortsRoot({...ports},root,a.factory),/invalidated_snapshot/);assert.throws(()=>api.assertRustChatIOPortsRoot(ports,other,a.factory),/invalidated_snapshot/);assert.throws(()=>api.assertRustChatIOPortsRoot(ports,root,b.factory),/invalidated_snapshot/);await a.host.closeAndDrain();await b.host.closeAndDrain();
});
test('original root callback cannot revoke and return Ok to pass ports association',async()=>{
 const f=await fixture();let armed=false,root;root=f.host.openChatIORoot(f.factory,()=>{if(armed)api.revokeRustChatIORoot(root)});const ports=api.createRustChatIOPorts(api.openRustChatIORoutingLease(root,f.gate),f.factory);armed=true;
 assert.throws(()=>api.assertRustChatIOPortsRoot(ports,root,f.factory),/invalidated_snapshot/);await f.host.closeAndDrain();
});

test('last original Root callback cannot revoke and return Ok after the previous association negative',async()=>{
 const f=await fixture();let armed=false,calls=0,root;root=f.host.openChatIORoot(f.factory,()=>{if(armed&&++calls===3)api.revokeRustChatIORoot(root)});const ports=api.createRustChatIOPorts(api.openRustChatIORoutingLease(root,f.gate),f.factory);armed=true;
 assert.throws(()=>api.assertRustChatIOPortsRoot(ports,root,f.factory),/invalidated_snapshot/);assert.equal(calls,3);await f.host.closeAndDrain();
});
test('callback-free original ports negative never invokes the Root witness and refuses retired or copied resources',async()=>{
 const f=await fixture();let calls=0;const root=f.host.openChatIORoot(f.factory,()=>{calls++});const ports=api.createRustChatIOPorts(api.openRustChatIORoutingLease(root,f.gate),f.factory);const before=calls;
 api.assertRustChatIOPortsNegative(ports);assert.equal(calls,before);assert.throws(()=>api.assertRustChatIOPortsNegative({...ports}),/invalidated_snapshot/);assert.equal(calls,before);api.revokeRustChatIORoot(root);assert.throws(()=>api.assertRustChatIOPortsNegative(ports),/invalidated_snapshot/);assert.equal(calls,before);await f.host.closeAndDrain();
});
