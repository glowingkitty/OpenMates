/**
 * CLI dispatch regression for Claude Code external-chat links.
 * A loopback HTTP double accepts Task creation; no real account, database or
 * Claude Code runtime is involved. Linking to claude:<session-uuid> must only
 * succeed inside that session (CLAUDE_CODE_SESSION_ID) and never send a
 * creator-attribution header, because Claude is not an assignee identity.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';

const SESSION='00000000-0000-4000-8000-00000000c1a0';

async function withCli(run:(cli:(args:string[],env:Record<string,string|undefined>)=>Promise<{code:number;stdout:string;stderr:string}>,requests:{method?:string;path?:string;raw:string;creator?:string|string[]}[])=>Promise<void>) {
  const home=mkdtempSync(join(tmpdir(),'claude-cli-link-'));
  const state=join(home,'.openmates'); mkdirSync(state);
  const master=Buffer.alloc(32,7);
  const requests:{method?:string;path?:string;raw:string;creator?:string|string[]}[]=[];
  const server=createServer((req,res)=>{
    let raw=''; req.on('data',chunk=>raw+=chunk);
    req.on('end',()=>{
      requests.push({method:req.method,path:req.url,raw,creator:req.headers['x-openmates-task-creator']});
      res.setHeader('content-type','application/json');
      if(req.method==='POST' && req.url==='/v1/user-tasks') res.end(JSON.stringify({task:{...JSON.parse(raw),version:1,status:'todo',position:0,created_at:1,updated_at:1}}));
      else {res.statusCode=404;res.end(JSON.stringify({error:'synthetic not found'}));}
    });
  });
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
  const address=server.address(); assert.ok(address && typeof address==='object');
  const apiUrl=`http://127.0.0.1:${address.port}`;
  writeFileSync(join(state,'session.json'),JSON.stringify({apiUrl,sessionId:'unit-session',wsToken:'unit-token',cookies:{auth_refresh_token:'unit-refresh'},masterKeyExportedB64:master.toString('base64'),hashedEmail:'unit-account',userEmailSalt:'unit-salt',createdAt:Date.now(),autoLogoutMinutes:null}));
  const cli=async (args:string[],extra:Record<string,string|undefined>)=>{
    const env:Record<string,string|undefined>={...process.env,HOME:home,OPENMATES_STATE_DIR:state,OPENMATES_API_URL:apiUrl,OPENMATES_API_KEY:'',TERM:'dumb'};
    delete env.CODEX_THREAD_ID; delete env.CLAUDE_CODE_SESSION_ID;
    try {
      const result=await promisify(execFile)('node',['dist/cli.js',...args],{cwd:fileURLToPath(new URL('..',import.meta.url)),env:{...env,...extra},timeout:30_000});
      return {code:0,stdout:result.stdout,stderr:result.stderr};
    } catch (error) {
      const failed=error as {code?:number;stdout?:string;stderr?:string};
      return {code:failed.code ?? 1,stdout:failed.stdout ?? '',stderr:failed.stderr ?? ''};
    }
  };
  try { await run(cli,requests); }
  finally {
    server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));
    rmSync(home,{recursive:true,force:true});
  }
}

// contract-test: supporting surface=cli assertions=tasks.conversation.single-owner-claim,tasks.external-chat.encrypted-context
test('Claude Code link on create requires the matching CLAUDE_CODE_SESSION_ID', async () => {
  await withCli(async (cli,requests)=>{
    const args=['tasks','create','--title','Claude linked work','--external-chat',`claude:${SESSION}`,'--json'];
    const outside=await cli(args,{});
    assert.notEqual(outside.code,0);
    assert.match(outside.stderr+outside.stdout,/Only the owning Claude Code session can claim a Task/);
    const other=await cli(args,{CLAUDE_CODE_SESSION_ID:'00000000-0000-4000-8000-00000000beef'});
    assert.notEqual(other.code,0);
    assert.match(other.stderr+other.stdout,/Only the owning Claude Code session/);
    const invalid=await cli(['tasks','create','--title','Bad','--external-chat','claude:not-a-uuid','--json'],{CLAUDE_CODE_SESSION_ID:'not-a-uuid'});
    assert.notEqual(invalid.code,0);
    assert.match(invalid.stderr+invalid.stdout,/session UUIDs/);
    assert.equal(requests.filter(item=>item.method==='POST').length,0,'rejected claims must not reach the API');

    const inside=await cli(args,{CLAUDE_CODE_SESSION_ID:SESSION});
    assert.equal(inside.code,0,inside.stderr);
    const posts=requests.filter(item=>item.method==='POST' && item.path==='/v1/user-tasks');
    assert.equal(posts.length,1);
    const body=JSON.parse(posts[0].raw);
    assert.equal(body.external_chat_provider,'claude');
    assert.match(body.external_chat_lookup_hash,/^[0-9a-f]{64}$/);
    assert.equal(body.assignee_identity ?? null,null,'Claude links never create a claude assignee identity');
    assert.equal(posts[0].creator,undefined,'no Codex creator attribution for Claude links');
    assert.ok(!posts[0].raw.includes(SESSION),'session id is encrypted locally');
    assert.ok(!posts[0].raw.includes('Claude Code session'),'default title is encrypted locally');
    const printed=JSON.parse(inside.stdout).task;
    assert.deepEqual(printed.external_chat,{provider:'claude',id:SESSION,title:'Claude Code session'});
  });
});
