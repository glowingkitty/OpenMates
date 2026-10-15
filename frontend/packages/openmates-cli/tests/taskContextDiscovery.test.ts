/** Send-time Task discovery is bounded; current chat work remains fresh and authorized. */
// contract-test-file: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { prepareCliJevContext, prefetchCliJevDiscovery } from '../src/cliJevContext.ts';
import type { UserTaskRecord } from '../src/client.ts';
const scope = { personal: true, teamId: null };
const task = (id: string, patch: Record<string, unknown> = {}) => ({ task_id:id,status:'in_progress',version:3,updated_at:10,...patch } as UserTaskRecord);
function fixture() {
  let session: Record<string, unknown> | null = {apiUrl:'https://example.invalid',sessionId:'session',hashedEmail:'owner',createdAt:1,masterKeyExportedB64:'test-key',activeTeamId:null};
  const calls = { directory:0, linked:[] as Record<string,unknown>[], exact:[] as string[], decrypted:[] as string[] };
  const client = {
    getSession() { if(!session)throw new Error('Not logged in');return session; },
    async listProjects() { return []; }, async getActiveProjectFocus() { return null; }, async getCustomRuleDocuments() {return [];},
    async listUserTaskDiscoveryPage(options: unknown) {assert.deepEqual(options,scope);calls.directory++;return [] as UserTaskRecord[];},
    async listUserTasks(options: Record<string,unknown>) {assert.deepEqual(options,{...scope,chatId:'chat',limit:100});calls.linked.push(options);return [] as UserTaskRecord[];},
    async getUserTask(id: string, options: unknown) {assert.deepEqual(options,scope);calls.exact.push(id);throw new Error('Not authorized');},
    async getTaskDependencies(_id: string, options:unknown) {assert.deepEqual(options,scope);return {dependencies:[] as Array<{source_ref:string;target_ref:string}>,blockers:[]};},
    async decryptTaskContextRecord(row:UserTaskRecord,options:unknown) {assert.deepEqual(options,scope);calls.decrypted.push(row.task_id);return {title:row.task_id,description:`revision ${row.version}`,linkedProjectIds:[]};},
    async listUserPlans() {return [] as any[];},
    async getUserPlan(_id:string,_options:unknown) {throw new Error('No Plan');},
    async decryptPlanContextSummary(_plan:unknown,_options:unknown) {return 'Approved context';},
  };
  return {client,calls,setSession(value:Record<string,unknown>|null){session=value;},get session(){return session;}};
}
// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('uses one discovery page for a >100 Task account and retains an old linked Task outside it without global paging',async()=>{
  const f=fixture(),inventory=Array.from({length:251},(_,i)=>task(`TASK-${i}`));
  f.client.listUserTaskDiscoveryPage=async(options)=>{assert.deepEqual(options,scope);f.calls.directory++;return inventory.slice(0,100);};
  f.client.listUserTasks=async(options)=>{assert.equal(options.chatId,'chat');assert.equal(options.limit,100);f.calls.linked.push(options);return [task('TASK-250',{primary_chat_id:'chat',status:'blocked',updated_at:1})];};
  const result=await prepareCliJevContext(f.client as never,'chat',scope);
  assert.equal(f.calls.directory,1);assert.equal(f.calls.linked.length,1);assert.equal(f.calls.exact.length,0);
  assert.equal(result.related_task_candidates?.length,24);assert.equal(result.related_task_candidates?.[0].task_id,'TASK-250');
});
// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('fetches an explicit owned dependency outside the bounded directory directly and excludes denied targets',async()=>{
  const f=fixture();f.client.listUserTasks=async()=>[task('TASK-LINKED',{primary_chat_id:'chat',status:'todo'})];
  f.client.getTaskDependencies=async()=>({dependencies:[{source_ref:'task:TASK-LINKED',target_ref:'task:TASK-DEPENDENCY'},{source_ref:'task:TASK-LINKED',target_ref:'task:TASK-DENIED'}],blockers:[]});
  f.client.getUserTask=async(id,options)=>{assert.deepEqual(options,scope);f.calls.exact.push(id);if(id==='TASK-DENIED')throw new Error('403');return task(id,{status:'done',updated_at:1});};
  const result=await prepareCliJevContext(f.client as never,'chat',scope);
  assert.deepEqual(f.calls.exact.sort(),['TASK-DENIED','TASK-DEPENDENCY']);
  assert.equal(result.related_task_candidates?.find(row=>row.task_id==='TASK-DEPENDENCY')?.explicit_dependency,true);
  assert.ok(!result.related_task_candidates?.some(row=>row.task_id==='TASK-DENIED'));
});
// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('refreshes supplied canonical Tasks and never treats short names as exact IDs on SDK-minted chats',async()=>{
  const f=fixture();f.client.getUserTask=async(id)=>{f.calls.exact.push(id);return task(id,{status:'done',version:9,updated_at:1});};
  const result=await prepareCliJevContext(f.client as never,'new-chat',scope,{related_task_candidates:[{task_id:'12345678-1234-4234-8234-123456789012',title:'Unverified',summary:'Unverified',project_id:null,status:'done',changed_at:1,revision:'1',explicit_dependency:true}]},'Explain @TASK-NAMED',{sdkMintedChatId:true});
  assert.deepEqual(f.calls.exact.sort(),['12345678-1234-4234-8234-123456789012']);assert.equal(f.calls.linked.length,0);
  assert.deepEqual(result.related_task_candidates?.map(row=>row.task_id).sort(),['12345678-1234-4234-8234-123456789012']);
  assert.ok(result.related_task_candidates?.every(row=>row.summary==='revision 9'&&row.revision==='9'&&!row.explicit_dependency));
});
// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('starts independent Plan discovery before the linked Task read completes and rejects a changed approved revision',async()=>{
  const f=fixture();let release!:(rows:UserTaskRecord[])=>void,planStarted=false;
  f.client.listUserTasks=async()=>new Promise(resolve=>{release=resolve;});
  f.client.listUserPlans=async()=>{planStarted=true;return [];};
  let plan={plan_id:'plan',status:'approved',approval_state:'approved',approved_revision_id:'r1',submitted_revision_id:'r1',version:1,primary_chat_id:'other-chat'};
  f.client.getUserTask=async(id)=>task(id,{primary_chat_id:'chat',status:'todo',plan_id:'plan'});
  f.client.getUserPlan=async()=>({...plan}) as never;
  f.client.decryptPlanContextSummary=async()=>{plan={...plan,version:2,approved_revision_id:'r2',submitted_revision_id:'r2'};return 'Old approved summary';};
  const pending=prepareCliJevContext(f.client as never,'chat',scope);await Promise.resolve();assert.equal(planStarted,true);
  release([task('TASK-PLAN',{primary_chat_id:'chat',status:'todo',plan_id:'plan'})]);
  const result=await pending;assert.equal(result.accepted_plan_context,null);assert.equal(result.related_task_candidates?.[0].task_id,'TASK-PLAN');
});
// contract-test: supporting surface=cli assertions=auth.session.isolation
for(const change of ['logout','account','team'])it(`rejects old context after ${change} changes during the discovery read`,async()=>{
  const f=fixture();f.client.listUserTaskDiscoveryPage=async()=>{if(change==='logout')f.setSession(null);else f.setSession({...f.session,[change==='account'?'hashedEmail':'activeTeamId']:'changed'});return [task('TASK-PRIVATE')];};
  await assert.rejects(prepareCliJevContext(f.client as never,'chat',scope),/Task context workspace changed/);
});
// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('reads fresh discovery revisions on every turn without cached positive access or per-hint exact reads',async()=>{
  const f=fixture();let revision=1;
  f.client.listUserTaskDiscoveryPage=async()=>{f.calls.directory++;return [task('TASK-HINT',{version:revision})];};
  assert.equal((await prepareCliJevContext(f.client as never,'chat',scope)).related_task_candidates?.[0].revision,'1');
  revision=2;assert.equal((await prepareCliJevContext(f.client as never,'chat',scope)).related_task_candidates?.[0].revision,'2');
  f.client.listUserTaskDiscoveryPage=async()=>{throw new Error('403');};
  assert.deepEqual((await prepareCliJevContext(f.client as never,'chat',scope)).related_task_candidates,[]);
  assert.equal(f.calls.exact.length,0);
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.approval.revision-bound,auth.session.isolation
it('starts independent fresh discovery once and retains final active-focus revalidation at consumption', async () => {
  const f = fixture(); let focuses = 0, plans = 0;
  f.client.getActiveProjectFocus = async () => { focuses++; return null; };
  f.client.listUserPlans = async () => { plans++; return []; };
  const ticket = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  assert.equal(f.calls.directory, 1); assert.equal(f.calls.linked.length, 1);
  assert.equal(focuses, 1); assert.equal(plans, 1); assert.deepEqual(f.calls.decrypted, []);
  await prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted message', { prefetchedDiscovery: ticket });
  assert.equal(f.calls.directory, 1); assert.equal(f.calls.linked.length, 1); assert.equal(plans, 1);
  assert.equal(focuses, 2, 'final active focus must be read after discovery, never prefetched away');
  await assert.rejects(prepareCliJevContext(f.client as never, 'chat', scope, undefined, '', { prefetchedDiscovery: ticket }), /Invalid same-send/);
});

// contract-test: supporting surface=cli assertions=auth.session.isolation
for (const change of ['logout', 'account', 'team']) it(`rejects ${change} between eager discovery and consumption`, async () => {
  const f = fixture(); const ticket = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  if (change === 'logout') f.setSession(null);
  else f.setSession({ ...f.session, [change === 'account' ? 'hashedEmail' : 'activeTeamId']: 'changed' });
  await assert.rejects(prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted', { prefetchedDiscovery: ticket }), /workspace changed/);
  assert.deepEqual(f.calls.decrypted, []);
});

// contract-test: supporting surface=cli assertions=auth.session.isolation
for (const change of ['chat', 'scope', 'client']) it(`rejects discovery ticket reused for another ${change}`, async () => {
  const f = fixture(); const ticket = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  await assert.rejects(prepareCliJevContext((change === 'client' ? fixture().client : f.client) as never,
    change === 'chat' ? 'another-chat' : 'chat', change === 'scope' ? { teamId: 'another-team' } : scope,
    undefined, 'Redacted', { prefetchedDiscovery: ticket }), /Invalid same-send/);
  assert.deepEqual(f.calls.decrypted, []);
});

// contract-test: supporting surface=cli assertions=plans.approval.revision-bound,auth.session.isolation
it('treats prefetched approved Plan rows as discovery and still reloads exact current approval revisions', async () => {
  const f = fixture(); let exact = 0;
  const plan = { plan_id: 'plan', primary_chat_id: 'chat', version: 1, status: 'active', approval_state: 'approved',
    submitted_revision_id: 'revision-1', approved_revision_id: 'revision-1' };
  f.client.listUserPlans = async () => [plan];
  (f.client as any).getUserPlan = async () => { exact++; return { ...plan, version: 2, submitted_revision_id: 'revision-2', approved_revision_id: 'revision-2' }; };
  const ticket = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  const result = await prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted', { prefetchedDiscovery: ticket });
  assert.equal(exact, 2); assert.equal(result.accepted_plan_context?.version, 2);
  assert.equal(result.accepted_plan_context?.approved_revision_id, 'revision-2');
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,auth.session.isolation
it('fetches fresh Task revisions for each new same-chat discovery ticket', async () => {
  const f = fixture(); let revision = 3;
  f.client.listUserTaskDiscoveryPage = async () => [task('TASK', { version: revision })];
  const first = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  const a = await prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted', { prefetchedDiscovery: first });
  revision = 4;
  const second = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  const b = await prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted', { prefetchedDiscovery: second });
  assert.equal(a.related_task_candidates?.[0].revision, '3'); assert.equal(b.related_task_candidates?.[0].revision, '4');
});

// contract-test: supporting surface=cli assertions=auth.session.isolation
it('does not start dependent Project metadata reads after the discovery owner changes', async () => {
  const f = fixture(); let resolveFocus!: (value: unknown) => void, projectReads = 0;
  (f.client as any).getActiveProjectFocus = () => new Promise(resolve => { resolveFocus = resolve; });
  (f.client as any).getProject = async () => { projectReads++; return {}; };
  const ticket = prefetchCliJevDiscovery(f.client as never, 'chat', scope);
  f.setSession({ ...f.session, hashedEmail: 'changed-owner' });
  resolveFocus({ project_id: 'private-project', team_id: null });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(projectReads, 0);
  await assert.rejects(prepareCliJevContext(f.client as never, 'chat', scope, undefined, 'Redacted', { prefetchedDiscovery: ticket }), /workspace changed/);
});
