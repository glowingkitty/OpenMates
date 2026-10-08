/* eslint-disable @typescript-eslint/no-require-imports */
/** Real graphical-terminal proof for contextual fullscreen actions and Settings. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
import type {ChromeFixture} from './cli-tui-chrome-settings-fixture';

const {test,expect,email,password,otpKey,captureProof,installRecorderDeps,requireIsolatedCliBuild,
	workflowApiUrl,createWorkflowCliHome,skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {loginWorkflowCliViaPair,removeWorkflowCliHome} = require('./helpers/workflow-cli-e2e-helpers');
const {makeChromeFixture,persistChromeFixture,seedChromeEmbedAndCache,chromeShareState,chromeTaskState} = require('./cli-tui-chrome-settings-fixture');
const fs = require('node:fs');
const path = require('node:path');

const ROOT=path.resolve(__dirname,'../../../..');
const PROFILE='cli-terminal';
const contract={
	id:'cli-tui-chrome-settings-real-terminal',title:'Fullscreen actions and responsive Settings',surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'centered-chat',text:'The chat title and header controls stay centered at wide and narrow terminal sizes.',checkpoint:'chat-narrow',devices:[PROFILE]},
		{id:'centered-embed',text:'The code embed title stays centered, and Back remains clickable in the narrow header.',checkpoint:'embed-narrow',devices:[PROFILE]},
		{id:'private-share',text:'Share presents private choices without generating a link; the saved chat remains private after the first recording.',checkpoint:'share-config',devices:[PROFILE]},
		{id:'actions',text:'Copy provides selectable text and Download asks before overwriting a local file.',checkpoint:'overwrite-prompt',devices:[PROFILE]},
		{id:'origin',text:'The code embed Back control returns to its originating chat; Close returns to Chats.',checkpoint:'embed-back',devices:[PROFILE]},
	],
	assertions:[
		{id:'terminal-chrome.navigation.origin-preserved',checkpoint:'embed-back',visual:'Centered, responsive chat and embed headers retain clickable Back and Close targets; Back returns to the originating chat.',devices:[PROFILE]},
		{id:'terminal-chrome.share.explicit-and-private',checkpoint:'share-config',visual:'A real Share click opens configuration; only an explicit later Generate Link marks this fixture chat shared.',devices:[PROFILE]},
		{id:'terminal-chrome.actions.contextual-and-functional',checkpoint:'overwrite-prompt',visual:'Real Copy and Download clicks show a text fallback, the CLI destination, and overwrite confirmation.',devices:[PROFILE]},
	],tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};
const settingsContract={
	id:'cli-tui-settings-real-terminal',title:'Chat settings, QR sharing and responsive Settings',surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'configure',text:'Choose expiration, password and sensitive-data settings before generating a link.',checkpoint:'share-open',devices:[PROFILE]},
		{id:'qr',text:'Share offers a complete QR code, resize guidance and a copyable link.',checkpoint:'share-qr-open',devices:[PROFILE]},
		{id:'devices',text:'Device approval uses the browser.',checkpoint:'devices',devices:[PROFILE]},
		{id:'restore',text:'Closing Settings preserves the unsent draft.',checkpoint:'settings-closed',devices:[PROFILE]},
		{id:'logout',text:'Logout clears the private chat and draft.',checkpoint:'logout-cleared',devices:[PROFILE]},
	],
	assertions:[
		{id:'terminal-chrome.share.explicit-and-private',checkpoint:'share-open',visual:'Share initially shows expiration, password, sensitive-data choices and Generate Link, followed by explicit link actions.',devices:[PROFILE]},
		{id:'terminal-pointer.viewport-coherent',checkpoint:'share-qr-open',visual:'Share shows a complete QR matrix with Back and Copy controls; the narrow view offers resize or copy guidance.',devices:[PROFILE]},
		{id:'terminal-settings.navigation.web-hierarchy-and-capabilities',checkpoint:'devices',visual:'Devices explains browser approval and provides Open web destination.',devices:[PROFILE]},
		{id:'terminal-settings.shell.responsive-and-restorable',checkpoint:'settings-closed',visual:'The settled full-width chat is restored with Keep this unsent draft in its composer.',devices:[PROFILE]},
		{id:'terminal-settings.operations.validated-and-owner-scoped',checkpoint:'logout-cleared',visual:'The signed-out examples view says Session ended and no longer shows the private chat or draft.',devices:[PROFILE]},
	],tutorial:contract.tutorial,
};

function frame(recording:any,name:string):string{return recording.frame(name).join('\n');}
function settingsPanelText(recording:any,name:string):string {
	return recording.frame(name).map((row:string)=>row.split('│')[0].trim()).join('');
}
function centeredHeader(recording:any,name:string,title:string,subtitle:string,meta?:string):{columns:number;rows:number} {
	const frameRows:string[]=recording.frame(name),columns=frameRows[0]?.length ?? 0,rows=frameRows.length;
	expect(columns).toBeGreaterThan(40);
	const breadcrumbRow=frameRows.findIndex(row=>row.includes('‹ Back'));
	const actionsRow=frameRows.findIndex(row=>row.includes('× Close'));
	const heroRow=frameRows.findIndex(row=>row.trim()===title);
	const subtitleRow=frameRows.findIndex((row,index)=>index>heroRow&&row.includes(subtitle));
	const metaRow=meta?frameRows.findIndex((row,index)=>index>subtitleRow&&row.includes(meta)):-1;
	expect(breadcrumbRow,`${name} shows the fullscreen breadcrumb`).toBeGreaterThanOrEqual(0);
	expect(actionsRow,`${name} shows the fullscreen actions`).toBeGreaterThan(breadcrumbRow);
	expect(heroRow,`${name} shows the complete hero title`).toBeGreaterThan(actionsRow);
	expect(subtitleRow,`${name} shows the hero subtitle`).toBe(heroRow+1);
	if(meta)expect(metaRow,`${name} shows the category and time metadata`).toBe(subtitleRow+1);
	for (const index of [breadcrumbRow,actionsRow,heroRow,subtitleRow,...meta?[metaRow]:[]]) {
		const row=frameRows[index],visible=row.trim(),start=row.indexOf(visible);
		expect(row.length,`${name} header row ${index+1} fits the terminal`).toBe(columns);
		expect(Math.abs(start+visible.length/2-columns/2),`${name} row ${index+1} is centered`).toBeLessThanOrEqual(1.5);
	}
	const topPadding=rows>=28&&columns>=48?2:rows>=18&&columns>=28?1:0;
	// Both fixture heroes have one-line title/subtitle (and the chat has metadata).
	// The fullscreen header contributes one spacer above the responsive hero.
	expect(heroRow-actionsRow,`${name} uses viewport-sized hero padding`).toBe(2+topPadding);
	return {columns,rows};
}
function clickedVisibleTarget(recording:any,from:string,step:string,label:string):void {
	const rows:string[]=recording.frame(from);
	const pointer=recording.manifest.input_checkpoints.find((point:any)=>point.name===step)?.pointer;
	expect(pointer,`${step} has a real pointer target`).toBeTruthy();
	const row=rows.findIndex(value=>value.includes(label));
	expect(row,`${from} shows ${label}`).toBeGreaterThanOrEqual(0);
	expect(pointer.row).toBe(row+1);
	expect(pointer.column).toBeGreaterThanOrEqual(rows[row].indexOf(label)+1);
	expect(pointer.column).toBeLessThanOrEqual(rows[row].indexOf(label)+label.length);
	expect(pointer.columns).toBe(rows[row].length);
	expect([pointer.window_width,pointer.window_height]).toEqual([640,360]);
}
function nestedInfo(testInfo:any,label:string,canonical=false):any {
	// One Playwright result may contain only one canonical proof timeline. Keep
	// both real recordings, with the Settings timeline as the approved proof.
	return {outputPath:(...parts:string[])=>testInfo.outputPath(label,...parts),
		attach:(name:string,options:unknown)=>testInfo.attach(canonical?name:label+'-'+name,options)};
}

// contract-test: supporting surface=cli assertions=terminal-chrome.navigation.origin-preserved,terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private,terminal-settings.shell.responsive-and-restorable,terminal-settings.navigation.web-hierarchy-and-capabilities,terminal-settings.operations.validated-and-owner-scoped,terminal-pointer.viewport-coherent
test('records real fullscreen header and Settings clicks on an owner-encrypted chat',async({page}:{page:any},testInfo:any)=>{
	test.setTimeout(420_000);
	test.skip(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted'||process.env.CI_TEST_MODE!=='e2e',
		'Requires isolated GitHub product stack and real graphical terminal');
	skipWithoutCredentials(test,email,password,otpKey);
	const cli=requireIsolatedCliBuild();installRecorderDeps();
	const apiUrl=workflowApiUrl(),home=createWorkflowCliHome('tui-chrome-settings');
	let fixture:ChromeFixture|undefined,downloadPath:string|undefined;
	let proofError:unknown;
	try{
		await loginWorkflowCliViaPair(page,apiUrl,home,'CLI_TUI_CHROME_SETTINGS_PROOF');
		const chat:ChromeFixture=makeChromeFixture(apiUrl,home,cli);fixture=chat;
		persistChromeFixture(chat,'seed');seedChromeEmbedAndCache(apiUrl,home,cli,chat);
		expect(chromeShareState(chat)).toEqual({isShared:false,sharePii:false});
		downloadPath=path.join(ROOT,chat.title+'.md');
		const sentinel='Original fixture file; cancel must retain this.\n';
		const taskTitle='Chrome task '+chat.chatId.slice(0,8);
		fs.writeFileSync(downloadPath,sentinel,{flag:'wx',mode:0o600});
		const first:ProofStep[]=[
			{name:'landing',wait_for:'DAILY INSPIRATION',hold_ms:300},
			{name:'chat-command',text:'/chat '+chat.chatId},
			{name:'chat-open',key:'Return',wait_for:'Chrome proof code',hold_ms:450},
			{name:'chat-narrow-bottom',resize:{width:640,height:360},wait_for:chat.title,hold_ms:200},
			{name:'chat-narrow',key:'Home',wait_for:'Private terminal chrome proof.',hold_ms:350},
			{name:'chat-narrow-more',click:{text:'More'},wait_for:'More actions',hold_ms:180},
			{name:'chat-narrow-more-dismiss',key:'Escape',wait_for:'× Close',wait_for_absent:'More actions',hold_ms:150},
			{name:'chat-narrow-end',key:'End',wait_for:'Chrome proof code',hold_ms:150},
			{name:'chat-wide',resize:{width:1280,height:720},wait_for:chat.title,hold_ms:350},
			{name:'header-focus',key:'alt+h',wait_for:'Enter activate',hold_ms:150},
			{name:'composer-focus',click:{text:'Ask a follow-up'},wait_for:'Ask a follow-up',wait_for_absent:'Enter activate',hold_ms:150},
			{name:'share-config',click:{text:'Share'},wait_for:'Share settings',hold_ms:200},
			{name:'share-duration',click:{text:'Expiration: Never'},wait_for:'Expiration: 1 minute',hold_ms:150},
			{name:'share-dismiss',key:'Escape',wait_for:'× Close',wait_for_absent:'Share settings',hold_ms:200},
			{name:'copy-open',click:{text:'Copy'},wait_for:'Copy text',hold_ms:200},
			{name:'copy-close',key:'Escape',wait_for:'× Close',wait_for_absent:'Copy text',hold_ms:150},
			{name:'download-open',click:{text:'Download'},wait_for:'Download to this CLI machine',hold_ms:200},
			{name:'overwrite-prompt',click:{text:'Save'},wait_for:'Overwrite existing file?',hold_ms:300},
			{name:'overwrite-cancel',key:'Escape',wait_for:'× Close',wait_for_absent:'Download to this CLI machine',hold_ms:150},
			{name:'more-open',click:{text:'More'},wait_for:'More actions',hold_ms:200},
			{name:'more-dismiss',key:'Escape',wait_for:'× Close',wait_for_absent:'More actions',hold_ms:150},
			{name:'embed-open',click:{text:'Chrome proof code'},wait_for:'export const chromeProof',hold_ms:350},
			{name:'embed-narrow',resize:{width:640,height:360},wait_for:'code · '+chat.embedId.slice(0,8),hold_ms:350},
			{name:'embed-back',click:{text:'‹ Back'},wait_for:'Chrome proof code',hold_ms:250},
			{name:'chat-return-wide',resize:{width:1280,height:720},wait_for:chat.title,hold_ms:300},
			{name:'chat-close',click:{text:'× Close'},wait_for:'DAILY INSPIRATION',hold_ms:250},
			{name:'exit-command',text:'/exit'},
			{name:'exit',key:'Return'},
		];
		const firstRecording=await captureProof(apiUrl,home,cli,first,contract,nestedInfo(testInfo,'header'));
		const chatWide=centeredHeader(firstRecording,'chat-open',chat.title,'Private terminal chrome proof.','General Knowledge');
		const chatNarrow=centeredHeader(firstRecording,'chat-narrow',chat.title,'Private terminal chrome proof.','General Knowledge');
		const embedWide=centeredHeader(firstRecording,'embed-open','code',chat.embedId.slice(0,8));
		const embedNarrow=centeredHeader(firstRecording,'embed-narrow','code',chat.embedId.slice(0,8));
		expect(chatWide.columns).toBeGreaterThan(chatNarrow.columns);
		expect(embedWide.columns).toBeGreaterThan(embedNarrow.columns);
		expect(chatWide.rows).toBeGreaterThan(chatNarrow.rows);
		expect(embedWide.rows).toBeGreaterThan(embedNarrow.rows);
		clickedVisibleTarget(firstRecording,'chat-narrow','chat-narrow-more','More');
		clickedVisibleTarget(firstRecording,'embed-narrow','embed-back','‹ Back');
		expect(frame(firstRecording,'header-focus')).toContain('Enter activate');
		expect(frame(firstRecording,'composer-focus')).not.toContain('Enter activate');
		expect(frame(firstRecording,'share-config')).toContain('Generate Link');
		expect(frame(firstRecording,'share-config')).toContain('Include sensitive data: No');
		expect(frame(firstRecording,'share-config')).not.toContain('Copy Link');
		expect(frame(firstRecording,'copy-open')).toContain('Select text above if clipboard delivery was not confirmed.');
		expect(frame(firstRecording,'copy-open')).toContain('Show the safe code snippet.');
		expect(frame(firstRecording,'download-open')).toContain('Destination:');
		expect(frame(firstRecording,'overwrite-prompt')).toContain('Overwrite existing file?');
		expect(frame(firstRecording,'more-open')).toContain('More actions');
		expect(frame(firstRecording,'embed-open')).toContain('export const chromeProof = true;');
		expect(frame(firstRecording,'embed-back')).toContain(chat.title);
		expect(frame(firstRecording,'embed-back')).toContain('Chrome proof code');
		expect(frame(firstRecording,'chat-close')).toContain('DAILY INSPIRATION');
		expect(fs.readFileSync(downloadPath,'utf8')).toBe(sentinel);
		expect(chromeShareState(chat)).toEqual({isShared:false,sharePii:false});
		await firstRecording.attest();

		const second:ProofStep[]=[
			{name:'landing',wait_for:'DAILY INSPIRATION',hold_ms:250},
			{name:'chat-command',text:'/chat '+chat.chatId},
			{name:'chat-open',key:'Return',wait_for:'Chrome proof code',hold_ms:400},
			{name:'chat-settings-open',click:{text:'Chat settings'},wait_for:'Chat settings ·',hold_ms:200},
			{name:'chat-tasks',click:{text:'  Tasks',occurrence:1},wait_for:'Create task',hold_ms:150},
			{name:'task-create',click:{text:'Create task'},wait_for:'Task title: _',hold_ms:100},
			{name:'task-title-focus',click:{text:'Task title:'},wait_for:'Task title: _',hold_ms:100},
			{name:'task-title',text:taskTitle,wait_for:taskTitle,hold_ms:100},
			{name:'task-saved',click:{text:'Save task'},wait_for:'Mark done · '+taskTitle,hold_ms:200},
			{name:'task-done',click:{text:'Mark done · '+taskTitle},wait_for:'Undo done · '+taskTitle,hold_ms:200},
			{name:'chat-files',click:{text:'  Files'},wait_for:'Open or download an embedded result.',hold_ms:150},
			{name:'chat-usage',click:{text:'  Usage'},wait_for:'No usage entries for this chat.',hold_ms:150},
			{name:'chat-share-tab',click:{text:'  Share'},wait_for:'Share chat',hold_ms:150},
			{name:'chat-settings-close',key:'Escape',wait_for:'× Close',wait_for_absent:'Chat settings ·',hold_ms:250},
			{name:'download-open',click:{text:'Download'},wait_for:'Download to this CLI machine',hold_ms:150},
			{name:'save-prompt',click:{text:'Save'},wait_for:'Overwrite existing file?',hold_ms:200},
			{name:'file-saved',click:{text:'Overwrite existing file?'},wait_for:'Saved on this CLI machine:',hold_ms:250},
			{name:'draft',text:'Keep this unsent draft',hold_ms:250},
			{name:'settings-root',click:{text:'Settings'},wait_for:'Settings  /  Settings',hold_ms:300},
			{name:'interface',click:{text:'Interface'},wait_for:'Settings  /  Interface',hold_ms:200},
			{name:'language',click:{text:'Language'},wait_for:'Language code: en',hold_ms:350},
			{name:'field-edit',click:{text:'Language code:',occurrence:0},wait_for:'[edit]',hold_ms:150},
			{name:'invalid-text',text:'invalid',wait_for:'Save changes',hold_ms:150},
			{name:'edit-end',key:'Return',hold_ms:150},
			{name:'narrow',resize:{width:650,height:600},hold_ms:350},
			{name:'narrow-no-clickthrough',click:{row:20,column:68},hold_ms:300},
			{name:'wide-again',resize:{width:1280,height:720},hold_ms:350},
			{name:'invalid-save',click:{text:'Save changes'},wait_for:'Error:',hold_ms:200},
			{name:'back-interface',click:{text:'Back to Interface'},wait_for:'Settings  /  Interface',hold_ms:200},
			{name:'back-root',click:{text:'Back to Settings'},wait_for:'Settings  /  Settings',hold_ms:150},
			{name:'pre-share-settings-closed',click:{text:'Close Settings'},wait_for:'Keep this unsent draft',wait_for_absent:'Settings  /',hold_ms:500},
			// The canonical walkthrough starts at the settled Share state. Keep
			// every earlier native-setting/export interaction in the raw recording.
			{name:'share-open-action',click:{text:'Share'},wait_for:'Share settings',hold_ms:400},
			{name:'share-open',hold_ms:4000},
			{name:'share-generated',click:{text:'Generate Link'},wait_for:'Copy Link',hold_ms:500},
			{name:'share-qr-action',click:{text:'Show QR code'},wait_for:'Share QR code',hold_ms:400},
			{name:'share-qr-open',hold_ms:2000},
			{name:'share-qr-narrow',resize:{width:640,height:360},wait_for:'QR needs',hold_ms:2500},
			{name:'share-qr-wide',resize:{width:1280,height:720},wait_for:'Back to share',hold_ms:2000},
			{name:'share-qr-back',click:{text:'Back to share'},wait_for:'Share settings',hold_ms:250},
			{name:'share-url',click:{text:'Show URL'},wait_for:'Share URL',hold_ms:1000},
			{name:'url-close',key:'Escape',wait_for:'× Close',wait_for_absent:'Share URL',hold_ms:350},
			{name:'settings-for-devices',click:{text:'Settings'},wait_for:'Settings  /  Settings',hold_ms:200},
			{name:'developers',click:{text:'Developers'},wait_for:'Settings  /  Developers',hold_ms:200},
			{name:'devices',click:{text:'Devices'},wait_for:'Settings  /  Devices',hold_ms:2500},
			{name:'settings-close-action',click:{text:'Close Settings'},wait_for:'Keep this unsent draft',wait_for_absent:'Settings  /',hold_ms:400},
			{name:'settings-closed',hold_ms:2500},
			{name:'logout-settings',click:{text:'Settings'},wait_for:'Settings  /  Settings',hold_ms:200},
			{name:'logout-confirmation',click:{text:'Log out'},wait_for:'Log out of this CLI session?',hold_ms:250},
			{name:'logout-action',click:{text:'Confirm'},wait_for:'Session ended. Sign in to reopen your work.',wait_for_absent:chat.title,hold_ms:400},
			{name:'logout-cleared',hold_ms:2500},
			{name:'exit-command',text:'/exit'},
			{name:'exit',key:'Return'},
		];
		const settingsRecording=await captureProof(apiUrl,home,cli,second,settingsContract,nestedInfo(testInfo,'settings',true));
		expect(frame(settingsRecording,'chat-settings-open')).toContain('Plan');
		expect(frame(settingsRecording,'chat-settings-open')).toContain('Tasks');
		expect(frame(settingsRecording,'chat-settings-open')).toContain('Files');
		expect(frame(settingsRecording,'chat-settings-open')).toContain('Usage');
		expect(frame(settingsRecording,'chat-settings-open')).toContain('Share');
		expect(frame(settingsRecording,'chat-usage')).toContain('Total credits: 0');
		expect(frame(settingsRecording,'chat-files')).toContain('Download');
		expect(frame(settingsRecording,'task-saved')).toContain('0/1 tasks done');
		expect(frame(settingsRecording,'task-done')).toContain('1/1 tasks done');
		expect(chromeTaskState(chat)).toEqual({count:1,statuses:['done'],encrypted:true});
		expect(frame(settingsRecording,'share-qr-open')).toContain('Share QR code');
		expect(frame(settingsRecording,'share-qr-wide')).toMatch(/[▀▄█]/);
		expect(frame(settingsRecording,'share-qr-wide')).not.toContain('QR needs');
		expect(frame(settingsRecording,'share-qr-narrow').split('\n').map(row=>row.trim()).join(' ')).toContain('Resize terminal or copy the link.');
		expect(frame(settingsRecording,'share-qr-back')).toContain('Copy Link');
		expect(frame(settingsRecording,'share-generated')).toContain('Show URL');
		expect(frame(settingsRecording,'share-generated')).not.toContain('#key=');
		expect(frame(settingsRecording,'share-url')).toContain('/share/chat/');
		expect(frame(settingsRecording,'settings-root')).toContain('Interface');
		expect(frame(settingsRecording,'settings-root')).toContain('Developers');
		expect(frame(settingsRecording,'settings-root')).not.toMatch(/\d+\.\s+Account\b/);
		expect(frame(settingsRecording,'settings-root')).toContain(chat.title);
		expect(frame(settingsRecording,'language')).toContain('Changes the web app language.');
		for(const name of ['language','field-edit','narrow','wide-again']) {
			expect(settingsPanelText(settingsRecording,name)).not.toMatch(/account id:|is admin:|key iv:|credential version:|user email salt:|invoice counter:|auto topup/i);
		}
		expect(frame(settingsRecording,'field-edit')).toContain('[edit]');
		expect(frame(settingsRecording,'invalid-text')).toContain('invalid');
		expect(frame(settingsRecording,'narrow')).toContain('Settings  /  Language');
		expect(frame(settingsRecording,'narrow-no-clickthrough')).toContain('Settings  /  Language');
		expect(frame(settingsRecording,'wide-again')).toContain('invalid');
		expect(settingsPanelText(settingsRecording,'invalid-save')).toContain('Error: Use a language code such as en or de.');
		expect(settingsPanelText(settingsRecording,'devices')).toContain('Device approval is available in the browser.');
		expect(frame(settingsRecording,'devices')).toContain('Open web destination');
		expect(frame(settingsRecording,'settings-closed')).toContain('Keep this unsent draft');
		const oldDivider=settingsRecording.frame('language')[2].indexOf('│');
		expect(oldDivider).toBeGreaterThan(0);
		for(const row of settingsRecording.frame('settings-closed'))expect(row[oldDivider]).not.toBe('│');
		expect(frame(settingsRecording,'logout-confirmation')).toContain('Confirm');
		expect(frame(settingsRecording,'logout-confirmation')).toContain('Cancel');
		expect(frame(settingsRecording,'logout-cleared')).toContain('Session ended. Sign in to reopen your work.');
		expect(frame(settingsRecording,'logout-cleared')).not.toContain(chat.title);
		expect(frame(settingsRecording,'logout-cleared')).not.toContain('Keep this unsent draft');
		expect(fs.readFileSync(downloadPath,'utf8')).toContain('Show the safe code snippet.');
		expect(chromeShareState(chat)).toEqual({isShared:true,sharePii:false});
		await settingsRecording.attest();
	}catch(error){proofError=error;}
	const cleanupFailures:unknown[]=[];
	try{if(fixture)persistChromeFixture(fixture,'cleanup');}catch(error){cleanupFailures.push(error);}
	try{if(downloadPath)fs.rmSync(downloadPath,{force:true});}catch(error){cleanupFailures.push(error);}
	try{removeWorkflowCliHome(home);}catch(error){cleanupFailures.push(error);}
	if(cleanupFailures.length)throw new AggregateError(proofError?[proofError,...cleanupFailures]:cleanupFailures,'Chrome proof cleanup failed');
	if(proofError)throw proofError;
});
