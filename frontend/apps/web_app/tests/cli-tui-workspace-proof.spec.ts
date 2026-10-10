/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test, expect, email, password, otpKey, homeProofContract, captureProof, installRecorderDeps, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, runWorkflowCliJson, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {runWorkflowCli, workflowCliEnv} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
async function attachTaskPageError(response: any, testInfo: any, name: string) {
	if(response.ok())return;
	let detail='non-JSON response';
	try {
		const failure=await response.json();
		detail=typeof failure.detail==='string'?failure.detail:'non-string detail';
	} catch { /* Plain server errors must retain status without exposing the body. */ }
	const classification=detail.replace(/[A-Za-z0-9_-]{32,}/g,'<redacted>').replace(/[^\s@]+@[^\s@]+/g,'<email>').slice(0,256);
	await testInfo.attach(name,{body:JSON.stringify({status:response.status(),classification}),contentType:'application/json'});
}
// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,workspace-shell.nav.released-surfaces-visible,tasks.surface.semantic-parity,projects.surface.semantic-parity,workflows.surface.semantic-parity
test('records the real terminal Chats, Tasks, Projects, Workflows, and Apps homes', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(240_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-proof-homes'), fixture = newFixture();
  fixture.projectName=fixture.projectName.replace('Terminal proof project','Proof project');
  fixture.workflowTitle=fixture.workflowTitle.replace('Terminal proof workflow','Proof workflow');
	let secondTaskId:string|undefined;
	try {
		await seedWorkspace(page, apiUrl, home, fixture, true);
		const secondTask=(await runWorkflowCliJson(apiUrl,home,['tasks','create','--title','Second paged terminal task','--assign','user','--project',fixture.projectId!],'create second paged task')).task;
		secondTaskId=secondTask.task_id;
		const taskPageUrl=`${apiUrl}/v1/user-tasks?project_id=${fixture.projectId}&paginate=true&limit=1`;
		const firstPage=await page.request.get(taskPageUrl);
		await attachTaskPageError(firstPage,testInfo,'task-page-http-error');
		expect(firstPage.ok()).toBe(true);
		const firstBody=await firstPage.json();
		expect(firstBody.complete).toBe(false);
		expect(firstBody.tasks).toHaveLength(1);
		expect(firstBody.tasks[0].encrypted_title).toBeTruthy();
		expect(firstBody.tasks[0].title).toBeUndefined();
		expect(JSON.stringify(firstBody)).not.toContain(fixture.taskTitle);
		const lastPage=await page.request.get(`${taskPageUrl}&cursor=${encodeURIComponent(firstBody.next_cursor)}`);
		await attachTaskPageError(lastPage,testInfo,'task-cursor-http-error');
		expect(lastPage.ok()).toBe(true);
		const lastBody=await lastPage.json();
		expect(lastBody.complete).toBe(true);
		expect(lastBody.next_cursor).toBeNull();
		expect([...firstBody.tasks,...lastBody.tasks].map((task:{task_id:string})=>task.task_id).sort()).toEqual([fixture.taskId,secondTaskId].sort());
		const anonymous=await page.context().browser().newContext();
		try {
			const rejected=await anonymous.request.get(taskPageUrl);
			expect([401,403]).toContain(rejected.status());
		} finally {await anonymous.close();}
		// Use the real SDK page-size option; the CLI display limit does not control HTTP pages.
		const pagingSource=`const {pathToFileURL}=require('node:url');
			(async()=>{const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
				const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
				const batches=[],limits=[],sizes=[];const get=client.http.get.bind(client.http);
				client.http.get=async(url,...args)=>{const response=await get(url,...args);if(url.startsWith('/v1/user-tasks?')){limits.push(new URL(url,'http://localhost').searchParams.get('limit'));sizes.push(response.data.tasks.length);}return response;};
				const filters=process.argv[2]==='personal'?{personal:true,limit:1}:{projectId:process.argv[2],limit:1};
				const tasks=await client.listUserTasks(filters,{onPage:(rows,complete)=>{batches.push([rows.length,complete]);}});
				const projections=tasks.filter(task=>task.source==='workflow_run').map(task=>({id:task.task_id,workflowId:task.workflow_id}));
				process.stdout.write(JSON.stringify({ids:tasks.map(task=>task.task_id),projections,batches,limits,sizes}));
			})().catch(error=>{console.error(error.message);process.exit(1)});`;
		const paged=JSON.parse(execFileSync('node',['-e',pagingSource,path.join(path.dirname(candidateCli),'index.js'),fixture.projectId!],{
			env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:60_000,
		}).trim());
		expect(paged.ids.sort()).toEqual([fixture.taskId,secondTaskId].sort());
		expect(paged.batches).toEqual([[1,false],[2,true]]);
		expect(paged.limits).toEqual(['1','1']);
		expect(paged.sizes).toEqual([1,1]);
		expect(paged.projections).toEqual([]);
		// The fixture is scheduled in 2036: enabling it creates a future Task
		// projection without running a workflow or invoking any AI.
		const colored=await page.request.patch(`${apiUrl}/v1/workflows/${fixture.workflowId}`,{data:{category:'finance',enabled:true}});
		expect(colored.ok()).toBe(true);
		expect((await colored.json()).workflow.category).toBe('finance');
		const allPaged=JSON.parse(execFileSync('node',['-e',pagingSource,path.join(path.dirname(candidateCli),'index.js'),'personal'],{
			env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:60_000,
		}).trim());
		expect(allPaged.batches).toEqual([[1,false],[2,false],[3,true]]);
		expect(allPaged.sizes).toEqual([1,1,1]);
		expect(allPaged.limits).toEqual(['1','1','1']);
		expect(allPaged.projections).toHaveLength(1);
		expect(allPaged.projections[0].workflowId).toBe(fixture.workflowId);
		expect(allPaged.projections[0].id).toMatch(/^workflow-schedule:/);
		const steps: ProofStep[] = [
			{name: 'initial-closed', wait_for: 'Continue where you left off', hold_ms: 350},
			{name: 'inspiration-focus', key: 'ctrl+o', wait_for: 'Enter open', hold_ms: 400},
			{name: 'inspiration-next', key: 'Right', wait_for: 'DAILY INSPIRATION', hold_ms: 550},
			{name: 'composer-focus', key: 'shift+Tab'},
			{name: 'content-focus', key: 'shift+Tab'},
			{name: 'scroll-bottom', key: 'End', wait_for: '/search Search chats', hold_ms: 350},
			{name: 'scroll-top', key: 'Home', wait_for: 'DAILY INSPIRATION', hold_ms: 350},
			{name: 'chat-second', key: 'Right', wait_for: 'Chat 2 of 5', hold_ms: 350},
			{name: 'chat-third', key: 'Right', wait_for: 'Chat 3 of 5', hold_ms: 200},
			{name: 'chat-fourth', key: 'Right', wait_for: 'Chat 4 of 5', hold_ms: 500},
			{name: 'chat-open', key: 'Return', wait_for: 'Draft', hold_ms: 600},
			{name: 'clear-proof-draft', key: 'ctrl+u'},
			{name: 'chats-command', text: '/chats'},
			{name: 'chats-home', key: 'Return', wait_for: 'Chat 1 of 5', hold_ms: 200},
			{name: 'sidebar-open', key: 'ctrl+b', wait_for: '+ New chat', hold_ms: 1000},
			{name: 'sidebar-closed', key: 'ctrl+b', hold_ms: 150},
			{name: 'tasks-command', text: '/tasks'},
			{name: 'tasks-home', key: 'Return', wait_for: fixture.taskTitle, hold_ms: 1000},
			{name: 'tasks-scroll-end', key: 'End', wait_for: fixture.taskTitle, hold_ms: 250},
			{name: 'tasks-scroll-home', key: 'Home', wait_for: 'DAILY INSPIRATION', hold_ms: 250},
			{name: 'tasks-backlog', key: 'Left', wait_for: 'Backlog 1/5', hold_ms: 150},
			{name: 'tasks-todo', key: 'Right', wait_for: 'Todo 2/5', hold_ms: 150},
			{name: 'tasks-in-progress', key: 'Right', wait_for: 'In progress 3/5', hold_ms: 150},
			{name: 'tasks-blocked', key: 'Right', wait_for: 'Blocked 4/5', hold_ms: 150},
			{name: 'tasks-done', key: 'Right', wait_for: 'Done 5/5', hold_ms: 150},
			{name: 'projects-command', text: '/projects'},
			{name: 'projects-home', key: 'Return', wait_for: fixture.projectName, hold_ms: 1000},
			{name: 'workflows-command', text: '/workflows'},
			{name: 'workflows-home', key: 'Return', wait_for: fixture.workflowTitle, hold_ms: 1000},
			{name: 'apps-command', text: '/apps'},
			{name: 'apps-home', key: 'Return', wait_for: 'Browse websites', hold_ms: 1200},
			{name: 'apps-scroll-bottom', key: 'End', wait_for: 'Show all', hold_ms: 350},
			{name: 'apps-scroll-top', key: 'Home', wait_for: 'DAILY INSPIRATION', hold_ms: 500},
			{name: 'exit-command', text: '/exit'},
			{name: 'exit', key: 'Return'}
		];
		const recording = await captureProof(apiUrl, home, candidateCli, steps, homeProofContract, testInfo);
		expect(recording.through('initial-closed')).toContain('DAILY INSPIRATION');
		expect(recording.through('initial-closed')).toMatch(/Hey .+!/);
		expect(recording.through('initial-closed')).toContain('Continue where you left off');
		expect(recording.frame('initial-closed').join('\n')).not.toContain('+ New chat');
		expect(recording.segment('inspiration-focus', 'initial-closed')).toContain('Enter open');
		expect(recording.frame('sidebar-open').some((row: string) => row.indexOf('+ New chat') >= 0 && row.indexOf('+ New chat') < 27)).toBe(true);
		expect(recording.segment('chat-fourth', 'chat-third')).toContain('Chat 4 of 5');
		expect(recording.segment('chat-open', 'chat-fourth')).toMatch(/Plan a weekend|Review a project|Learn a concept|Organize a trip|Write a story/);
		// Fitted homes may emit no new rows at Home/End. Inspect the painted frame.
		for (const checkpoint of ['scroll-bottom', 'scroll-top']) {
			const frame=recording.frame(checkpoint).join('\n');
			expect(frame).toContain('DAILY INSPIRATION');
			expect(frame).toContain('/search Search chats');
		}
		for (const checkpoint of ['apps-home', 'apps-scroll-bottom', 'apps-scroll-top']) {
			const frame=recording.frame(checkpoint).join('\n');
			expect(frame).toContain('Show all');
			expect(frame).toContain('DAILY INSPIRATION');
			expect(frame).toContain('App 1 of 6');
		}
		expect(recording.segment('tasks-home', 'tasks-command')).toContain(fixture.taskTitle);
		expect(recording.segment('tasks-home', 'tasks-command')).toContain('DAILY INSPIRATION');
		expect(recording.frame('tasks-scroll-end').join('\n')).toContain(fixture.taskTitle);
		expect(recording.frame('tasks-scroll-home').join('\n')).toContain(fixture.taskTitle);
		for (const status of ['Backlog', 'Todo', 'In progress', 'Blocked', 'Done'])
			expect(recording.segment('tasks-done', 'tasks-command')).toContain(status);
		expect(recording.segment('projects-home', 'projects-command')).toContain(fixture.projectName);
    expect(recording.segment('projects-home', 'projects-command')).toContain('Project 1 of 1');
    expect(recording.segment('projects-home', 'projects-command')).toContain('←/→ choose project');
		expect(recording.segment('workflows-home', 'workflows-command')).toContain(fixture.workflowTitle);
    expect(recording.segment('workflows-home', 'workflows-command')).toContain('DAILY INSPIRATION');
    expect(recording.segment('workflows-home', 'workflows-command')).toContain('Workflow 1 of 1');
    expect(recording.segment('workflows-home', 'workflows-command')).toContain('←/→ choose workflow');
		// Inspect the real painted title row, rather than another pink inspiration row.
		const point=recording.manifest.input_checkpoints.find((checkpoint:{name:string})=>checkpoint.name==='workflows-home');
		const raw=Buffer.from(recording.transcript,'utf8').subarray(0,point.transcript_offset).toString('utf8');
		const frameEnd=raw.lastIndexOf('\x1b[?2026l'),frameStart=raw.lastIndexOf('\x1b[?2026h',frameEnd);
		// eslint-disable-next-line no-control-regex -- Verify actual terminal cell background on the workflow card.
		const cardRow=raw.slice(frameStart,frameEnd).split(/\x1b\[\d+;1H/).find((row:string)=>row.includes(fixture.workflowTitle));
		expect(cardRow).toContain('\x1b[48;2;17;145;6m');
		expect(recording.segment('apps-home', 'apps-command')).toContain('What app do you want to use?');
		expect(recording.segment('apps-home', 'apps-command')).toContain('Web');
		await recording.attest();
	} finally {
		if(secondTaskId)await runWorkflowCli(apiUrl,home,['tasks','delete',secondTaskId,'--confirm','--json']);
		await cleanupWorkspace(apiUrl, home, fixture);
	}
});
