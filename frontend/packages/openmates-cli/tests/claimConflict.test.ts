/**
 * Concurrent ownership conflict remains readable after durable admission.
 * Synthetic encrypted Tasks and a rejected transport replace any real account.
 * The successful path is not probed or changed by these failure-only lookups.
 * No model, browser, database or external request runs in this focused check.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {OpenMatesClient} from '../src/client.ts';
import {buildCreateUserTaskInput} from '../src/tasksCli.ts';
import {failureDisposition} from '../src/taskDelivery.ts';

test('a claim race reports the quoted Codex owner through the durable queue', async()=>{
  const owner='00000000-0000-0000-0000-000000000001';
  const master=Buffer.alloc(32,4);
  const task=await buildCreateUserTaskInput(master,{title:'Task',assign:'codex',externalChat:{provider:'codex',id:owner,title:'Landing - Header'}});
  const client=new OpenMatesClient({session:{apiUrl:'https://example.invalid',sessionId:'unit',wsToken:'unit',cookies:{},masterKeyExportedB64:master.toString('base64'),hashedEmail:'unit',userEmailSalt:'unit',createdAt:Date.now(),autoLogoutMinutes:null}});
  (client as any).http.patch=async()=>({ok:false,status:409,data:{detail:'TASK_ALREADY_LINKED'}});
  let reads=0;
  client.getUserTask=async()=>{reads++;return task;};
  let conflict;
  try {await client.updateUserTask(task.task_id,{version:1,external_chat_provider:'codex',external_chat_lookup_hash:'another'});}
  catch(error){conflict=error;}
  assert.equal(reads,1);
  assert.equal(conflict.status,409);
  assert.match(conflict.message,new RegExp(`"Landing - Header".*Codex chat ID: ${owner}`));
  assert.throws(()=>failureDisposition(conflict,null,Date.now()),new RegExp(`"Landing - Header".*Codex chat ID: ${owner}`));
});
