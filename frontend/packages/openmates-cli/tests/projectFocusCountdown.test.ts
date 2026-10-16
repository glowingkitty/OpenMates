/** Automatic Project activation confirms server authority before private reads. */
// contract-test-file: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { registerProjectFocusCountdown } from '../src/projectFocusCountdown.ts';
import { encryptWithAesGcmCombined } from '../src/crypto.ts';
const projectId = '11111111-1111-4111-8111-111111111111';
function wsFixture(autoAck = true) {
  const handlers = new Map<string, (value: unknown) => void>(), sent: Array<{type: string; payload: any}> = [];
  let close: (() => void) | undefined, removedClose = false;
  const sendWaiters: Array<{count:number;resolve:()=>void}> = [];
  return { handlers, sent, waitForSends: (count:number) => sent.length >= count ? Promise.resolve() : new Promise<void>(resolve=>sendWaiters.push({count,resolve})), close: () => close?.(), closeRemoved: () => removedClose, ws: { onMessageType(type: string, handler: (value: unknown) => void) { handlers.set(type, handler); return () => handlers.delete(type); },
    onClose(handler: () => void) { close = handler; return () => { removedClose = true; close = undefined; }; }, async sendAsync(type: string, payload: unknown) {
      sent.push({type, payload});
      for(const waiter of sendWaiters)if(sent.length>=waiter.count)waiter.resolve();
      if (autoAck && type === 'project_focus_decision') handlers.get('project_focus_decision_confirmed')?.(payload);
    } } };
}

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('waits four seconds, confirms the server request, then loads/decrypts the private default Focus and activates that exact request', async context => {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100_000 });
  const key = new Uint8Array(32).fill(4), calls: string[] = [], f = wsFixture();
  const encrypted = await encryptWithAesGcmCombined(JSON.stringify({ default_focus: { focus_id: 'private', instructions: 'Private Project goals' } }), key);
  const stop = registerProjectFocusCountdown({ ws: f.ws as never, chatId: 'chat', teamId: null, client: {
    async confirmProjectFocusCountdown(_project: string, input: Record<string, unknown>) { calls.push('confirm'); assert.equal(input.activation_request_id, 'request'); },
    async getProject() { calls.push('private-detail'); return { project: {} }; }, async getProjectSettings() { calls.push('private-settings'); return { encrypted_settings: encrypted, selection_required: false }; },
    async decryptProjectKey() { calls.push('private-key'); return key; }, async activateProjectFocus(_project: string, input: Record<string, unknown>) { calls.push('activate'); assert.equal(input.activation_request_id, 'request'); assert.equal(input.instruction, 'Private Project goals'); },
  } as never });
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'request', expires_at: 104 });
  context.mock.timers.tick(3999); assert.deepEqual(calls, []); context.mock.timers.tick(1);
  for (let attempt = 0; attempt < 15 && !calls.includes('activate'); attempt++) await new Promise(resolve => setImmediate(resolve));
  await stop.flush();
  assert.equal(calls[0], 'confirm'); assert.equal(calls.at(-1), 'activate');
  assert.deepEqual(f.sent, [{type:'project_focus_decision',payload:{chat_id:'chat',request_id:'request',accepted:true}}]);
  assert.equal(f.handlers.has('project_focus_decision_confirmed'),false); stop(); assert.equal(f.handlers.size,0); assert.equal(f.closeRemoved(),true);
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('rejects or expires without loading private Project context', async context => {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100_000 });
  const f = wsFixture(); let privateReads = 0, confirmed = 0, reject: (() => Promise<void>) | undefined;
  const stop = registerProjectFocusCountdown({ ws: f.ws as never, chatId: 'chat', teamId: null,
    onPending(value) { reject = value?.reject; }, client: { async confirmProjectFocusCountdown() { confirmed++; throw new Error('stale request'); }, async getProject() { privateReads++; } } as never });
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'cancelled', expires_at: 104 });
  await reject?.(); context.mock.timers.tick(4000); assert.equal(confirmed, 0); assert.equal(privateReads, 0); assert.deepEqual(f.sent,[{type:'project_focus_decision',payload:{chat_id:'chat',request_id:'cancelled',accepted:false}}]);
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'stale', expires_at: 108 });
  context.mock.timers.tick(4000); await new Promise(resolve => setImmediate(resolve)); assert.equal(confirmed, 1); assert.equal(privateReads, 0); stop();
});

const tick = () => new Promise<void>(resolve => setImmediate(resolve));
async function activationFixture(f: ReturnType<typeof wsFixture>, extra: Record<string, unknown> = {}) {
  const calls: string[] = [], errors: unknown[] = [], key = new Uint8Array(32).fill(7);
  const encrypted = await encryptWithAesGcmCombined(JSON.stringify({default_focus:{focus_id:'default',instructions:'Private'}}),key);
  const stop = registerProjectFocusCountdown({ws:f.ws as never,chatId:'chat',teamId:null,onError:error=>errors.push(error),client:{
    async confirmProjectFocusCountdown(){calls.push('confirm');},async getProject(){calls.push('detail');return {project:{}};},
    async getProjectSettings(){calls.push('settings');return {encrypted_settings:encrypted};},async decryptProjectKey(){return key;},
    async activateProjectFocus(){calls.push('activate');},
  } as never,...extra});
  const pending=(policy='delayed',id='request')=>f.handlers.get('focus_mode_pending')?.({chat_id:'chat',focus_id:'project-'+projectId,embed_id:id,
    expires_at:Date.now()/1000+(policy==='delayed'?4:1200),activation_policy:policy});
  return {stop,pending,calls,errors};
}

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('waits for the matching decision ACK and removes all temporary listeners',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(false),a=await activationFixture(f);a.pending();context.mock.timers.tick(4000);
  await f.waitForSends(1);
  assert.equal(f.sent.length,1);let finished=false;const done=a.stop.flush().then(()=>{finished=true;});
  f.handlers.get('project_focus_decision_confirmed')?.({chat_id:'other',request_id:'request'});await tick();assert.equal(finished,false);
  f.handlers.get('project_focus_decision_confirmed')?.({chat_id:'chat',request_id:'other'});await tick();assert.equal(finished,false);
  f.handlers.get('project_focus_decision_confirmed')?.({chat_id:'chat',request_id:'request'});await done;
  assert.equal(f.handlers.has('project_focus_decision_error'),false);a.stop();assert.equal(f.handlers.size,0);
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('surfaces correlated refusal, acknowledgement timeout and transport closure without hanging',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  for(const failure of ['error','timeout','close']){
    const f=wsFixture(false),a=await activationFixture(f);a.pending();context.mock.timers.tick(4000);
    await f.waitForSends(1);
    if(failure==='error')f.handlers.get('project_focus_decision_error')?.({chat_id:'chat',request_id:'request',code:'PROJECT_FOCUS_REQUIRED'});
    if(failure==='timeout')context.mock.timers.tick(20_000);
    if(failure==='close')f.close();
    await a.stop.flush();await tick();assert.ok(a.errors.length);a.stop();assert.equal(f.handlers.size,0);
  }
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('honors immediate policy but never approves an approval-policy request automatically',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(),a=await activationFixture(f);a.pending('immediate');context.mock.timers.tick(0);await a.stop.flush();
  assert.equal(f.sent[0]?.payload.accepted,true);a.stop();
  const g=wsFixture(),b=await activationFixture(g);b.pending('approval');context.mock.timers.tick(1200_000);
  assert.deepEqual(b.calls,[]);assert.deepEqual(g.sent,[]);assert.equal(b.errors.length,1);b.stop();
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('stale owner or turn prevents private reads and accepted decisions',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  let current=true;const f=wsFixture(),a=await activationFixture(f,{isCurrent:()=>current});a.pending();current=false;
  context.mock.timers.tick(4000);await a.stop.flush();assert.deepEqual(a.calls,[]);assert.deepEqual(f.sent,[]);assert.equal(a.errors.length,1);a.stop();
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('a replaced request cannot execute its old countdown',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(),a=await activationFixture(f);a.pending('delayed','old');a.pending('delayed','new');
  context.mock.timers.tick(4000);await a.stop.flush();assert.equal(f.sent.length,1);assert.equal(f.sent[0].payload.request_id,'new');a.stop();
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('decision delivery failure immediately reaches the active-send error callback',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(false);f.ws.sendAsync=async()=>{throw Error('closed during send');};
  let rejectActive!: (error:unknown)=>void;
  const active=new Promise<never>((_,reject)=>{rejectActive=reject;});void active.catch(()=>{});
  const a=await activationFixture(f,{onError:rejectActive});a.pending();context.mock.timers.tick(4000);
  await assert.rejects(active,/closed during send/);await a.stop.flush();a.stop();assert.equal(f.handlers.size,0);
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('stop before countdown work prevents private reads and removes the close hook',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(),a=await activationFixture(f);a.pending();a.stop();context.mock.timers.tick(4000);
  await a.stop.flush();assert.deepEqual(a.calls,[]);assert.deepEqual(f.sent,[]);assert.equal(f.closeRemoved(),true);
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('replacing an in-flight decision removes its ACK listeners without failing the newer request',async context=>{
  context.mock.timers.enable({apis:['setTimeout','Date'],now:100_000});
  const f=wsFixture(false),a=await activationFixture(f);a.pending('delayed','old');context.mock.timers.tick(4000);
  await f.waitForSends(1);
  a.pending('delayed','new');assert.equal(f.handlers.has('project_focus_decision_confirmed'),false);
  await tick();assert.deepEqual(a.errors,[]);context.mock.timers.tick(4000);
  await f.waitForSends(2);
  f.handlers.get('project_focus_decision_confirmed')?.({chat_id:'chat',request_id:'new'});await a.stop.flush();
  assert.deepEqual(a.errors,[]);assert.equal(f.sent[1].payload.request_id,'new');a.stop();
});
