// contract-test-file: tooling
/**
 * CLI dispatch regression for automatic Codex edit persistence.
 * A loopback HTTP double returns one encrypted fixture and rejects its write.
 * No real account, database, Codex daemon or product E2E is involved.
 * The command must report pending and retain ciphertext without a delivery flag.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {buildCreateUserTaskInput} from '../src/tasksCli.ts';

test('Codex edit queues a rejected transport without an explicit delivery flag', async () => {
  const home=mkdtempSync(join(tmpdir(),'codex-cli-queue-'));
  const state=join(home,'.openmates'); mkdirSync(state);
  const owner='00000000-0000-0000-0000-000000000001';
  const master=Buffer.alloc(32,7);
  const task=await buildCreateUserTaskInput(master,{title:'Original',assign:'codex',externalChat:{provider:'codex',id:owner,title:'Worker'}});
  const requests=[];
  const server=createServer((req,res)=>{
    let raw=''; req.on('data',chunk=>raw+=chunk);
    req.on('end',()=>{
      requests.push({method:req.method,path:req.url,raw});
      res.setHeader('content-type','application/json');
      if(req.method==='GET' && req.url===`/v1/user-tasks/${task.task_id}`) res.end(JSON.stringify({task}));
      else {res.statusCode=503;res.end(JSON.stringify({error:'synthetic unavailable'}));}
    });
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const address=server.address(); assert.ok(address && typeof address==='object');
  const apiUrl=`http://127.0.0.1:${address.port}`;
  writeFileSync(join(state,'session.json'),JSON.stringify({apiUrl,sessionId:'unit-session',wsToken:'unit-token',cookies:{auth_refresh_token:'unit-refresh'},masterKeyExportedB64:master.toString('base64'),hashedEmail:'unit-account',userEmailSalt:'unit-salt',createdAt:Date.now(),autoLogoutMinutes:null}));
  try {
    const result=await promisify(execFile)('node',['dist/cli.js','tasks','edit',task.task_id,'--title','Changed','--json'],{
      cwd:fileURLToPath(new URL('..',import.meta.url)),
      env:{...process.env,HOME:home,OPENMATES_STATE_DIR:state,OPENMATES_API_URL:apiUrl,OPENMATES_API_KEY:'',CODEX_THREAD_ID:owner,TERM:'dumb'},timeout:30_000,
    });
    const response=JSON.parse(result.stdout);
    assert.equal(response.delivery.status,'pending');
    assert.match(response.delivery.delivery_id,/^[a-f0-9]{64}$/);
    const account=readdirSync(join(state,'task-mutation-delivery'))[0];
    const record=JSON.parse(readFileSync(join(state,'task-mutation-delivery',account,`${response.delivery.delivery_id}.json`),'utf8'));
    assert.equal(record.mutation.taskId,task.task_id);
    assert.equal(record.uncertain,true);
    assert.equal(record.acknowledgement,undefined);
    assert.ok(record.mutation.input.encrypted_title);
    assert.ok(requests.some(item=>item.method==='PATCH'));
    assert.ok(requests.every(item=>!item.raw.includes('Changed')));
  } finally {
    server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));
    rmSync(home,{recursive:true,force:true});
  }
});
