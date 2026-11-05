#!/usr/bin/env node
// contract-test-file: infrastructure
// Offline transport fixtures only: this test never contacts OpenMates.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

test('discovers whitespace JSON references and newly queued source embeds through the authenticated SDK', () => {
  const directory = mkdtempSync(join(tmpdir(), 'code-run-probe-offline-'));
  const outer = '11111111-1111-1111-1111-111111111111';
  const source = '22222222-2222-2222-2222-222222222222';
  const manifest = '33333333-3333-3333-3333-333333333333';
  const execution = '44444444-4444-4444-4444-444444444444';
  const sdk = join(directory, 'sdk.mjs');
  const messages = [{ role: 'assistant', content: `\`\`\`json\n{ "embed_id" : \n "${outer}" }\n\`\`\`` }];
  writeFileSync(sdk, `
    const seen = new Set();
    export class OpenMatesClient {
      static load() { return new OpenMatesClient(); }
      hasSession() { return true; }
      getSession() { return {apiUrl:'https://api.dev.openmates.org'}; }
      async getChatMessages(id, options) {
        if (id !== 'owned-chat' || options.personal !== true) throw new Error('WrongChat');
        return {chat:{id},messages:${JSON.stringify(messages)}};
      }
      async getEmbed(id, options) {
        if (options.chatId !== 'owned-chat' || seen.has(id)) throw new Error('WrongScopeOrDuplicate');
        seen.add(id);
        if (id === '${outer}') return {embedId:id,content:{
          target_embed_id:'${source}',created_embed_ids:['${source}','${manifest}'],task_id:'${execution}'}};
        if (id === '${source}') return {embedId:id,content:{code:'fn main() {}',language:'rust'}};
        if (id === '${manifest}') return {embedId:id,content:{filename:'requirements.txt',code:'numpy'}};
        throw new Error('UnexpectedEmbed');
      }
      async getCodeRunStatus(path) {
        if (path !== '/v1/code/run/${execution}') throw new Error('NotExecution');
        return {execution_id:'${execution}',target_embed_id:'${source}',status:'finished',exit_code:0,
          artifacts:[{path:'outputs/chart.png',aes_key:'SECRET',download_url:'SECRET',native_render_payload:{aes_key:'SECRET'}}]};
      }
    }
  `);
  try {
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('./code_run_real_probe.mjs', import.meta.url))], {
      input: JSON.stringify({ api_url: 'https://api.dev.openmates.org', sdk_module: sdk, chat_id: 'owned-chat' }),
      encoding: 'utf8', timeout: 10_000,
      env: { ...process.env, OPENMATES_STATE_DIR: directory },
    });
    assert.equal(result.status, 0, result.stderr);
    const snapshot = JSON.parse(result.stdout);
    assert.deepEqual(snapshot.embeds.map(embed => embed.embedId), [outer, source, manifest]);
    assert.deepEqual(snapshot.errors, []);
    assert.equal(snapshot.executions.length, 1);
    assert.equal(snapshot.executions[0].target_embed_id, source);
    assert.equal(snapshot.executions[0].exit_code, 0);
    assert.ok(!result.stdout.includes('SECRET'));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
