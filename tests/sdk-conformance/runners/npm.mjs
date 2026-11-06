/** Execute real npm SDK code against shared synthetic vectors and fake transport. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
register(new URL('../../../frontend/packages/openmates-cli/tests/loader.mjs', import.meta.url));
const args = process.argv.slice(2); const option = name => args[args.indexOf(name) + 1];
const capability = option('--capability'); const filename = option('--fixture');
// BEGIN CLOSED GENERATED SKILLS DIAGNOSTIC
const GENERATED_DIAGNOSTIC_STAGES=Object.freeze(['arguments','fixture_read','fixture_decode','fixture_contract','sdk_import','vector_admission','fetch_install','client_constructor','generated_dispatch','response_assert','call_count_assert','method_assert','path_assert','body_assert','authorization_assert','fetch_restore','record_result','result_summary','emit_result','unclassified']);
const GENERATED_DIAGNOSTIC_VECTORS=Object.freeze(['none','generated-web-search']);
const GENERATED_DIAGNOSTIC_PRE_ADMISSION=Object.freeze(['arguments','fixture_read','fixture_decode','fixture_contract','sdk_import','vector_admission']);
const GENERATED_DIAGNOSTIC_SUITE_ONLY=Object.freeze([...GENERATED_DIAGNOSTIC_PRE_ADMISSION,'result_summary','emit_result']);
const GENERATED_DIAGNOSTIC_ERRORS=Object.freeze(['assertion','module_not_found','module_export_missing','unsupported_ts_syntax','syntax','type','reference','sdk_config','sdk_api','unclassified']);
const GENERATED_DIAGNOSTIC_GENERIC='npm SDK conformance failed: protocol.generated-skills.v1\n';
function generatedDiagnosticError(error){
  try{
    if(error===null||(typeof error!=='object'&&typeof error!=='function'))return 'unclassified';
    const own=(value,key)=>{const descriptor=Object.getOwnPropertyDescriptor(value,key);return descriptor&&Object.hasOwn(descriptor,'value')?descriptor.value:undefined;};
    const code=own(error,'code'),prototype=Object.getPrototypeOf(error),name=own(error,'name')??(prototype===null?undefined:own(prototype,'name'));
    if(code==='ERR_ASSERTION'||name==='AssertionError')return 'assertion';
    if(code==='ERR_MODULE_NOT_FOUND'||code==='MODULE_NOT_FOUND')return 'module_not_found';
    if(code==='ERR_PACKAGE_PATH_NOT_EXPORTED')return 'module_export_missing';
    if(code==='ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX')return 'unsupported_ts_syntax';
    if(name==='SyntaxError')return 'syntax';
    if(name==='TypeError')return 'type';
    if(name==='ReferenceError')return 'reference';
    if(name==='OpenMatesConfigError')return 'sdk_config';
    if(name==='OpenMatesApiError'||name==='OpenMatesSignupRequiredError')return 'sdk_api';
  }catch{}
  return 'unclassified';
}
function generatedDiagnosticLine(stage,vector,error){
  const safeStage=GENERATED_DIAGNOSTIC_STAGES.includes(stage)?stage:'unclassified';
  const safeVector=!GENERATED_DIAGNOSTIC_SUITE_ONLY.includes(safeStage)&&GENERATED_DIAGNOSTIC_VECTORS.includes(vector)?vector:'none';
  const safeError=GENERATED_DIAGNOSTIC_ERRORS.includes(error)?error:'unclassified';
  return `npm generated-skills diagnostic: stage=${safeStage};vector=${safeVector};error=${safeError}\n`;
}
// END CLOSED GENERATED SKILLS DIAGNOSTIC
let generatedDiagnosticStage='arguments',generatedDiagnosticVector='none';
try {
  assert.ok(args.includes('--fixture') && args.includes('--capability'));
  generatedDiagnosticStage='fixture_read';
  const bytes = readFileSync(filename); const fixtureSha256 = createHash('sha256').update(bytes).digest('hex');
  generatedDiagnosticStage='fixture_decode';
  const document = JSON.parse(bytes);
  const FLAT_FIXTURES = ['sdk.api-key-operations.v1', 'sdk.api-key-memories.v1'];
  const suite = FLAT_FIXTURES.includes(capability) ? document : document.capabilities[capability];
  generatedDiagnosticStage='fixture_contract';
  assert.ok(suite && Array.isArray(suite.vectors));
  const source = name => new URL(`../../../frontend/packages/openmates-cli/src/${name}.ts`, import.meta.url);
  const results = [];
  if (capability === 'crypto.aes-gcm-combined.v1') {
    const crypto = await import(source('sdkCrypto'));
    for (const vector of suite.vectors) {
      const key = new Uint8Array(Buffer.from(vector.key_b64, 'base64'));
      assert.equal(await crypto.decryptWithAesGcmCombined(vector.ciphertext_b64, key), vector.plaintext);
      const encrypted = await crypto.encryptWithAesGcmCombined(vector.plaintext, key);
      assert.equal(await crypto.decryptWithAesGcmCombined(encrypted, key), vector.plaintext);
      const written = Buffer.from(encrypted, 'base64');
      assert.equal(written.subarray(0, 2).toString(), 'OM');
      assert.deepEqual(written.subarray(2, 6), Buffer.from(crypto.sdkKeyFingerprint(key)));
      assert.equal(Buffer.from(await crypto.decryptBytesWithAesGcm(vector.ciphertext_b64, key)).toString('utf8'), vector.plaintext);
      assert.equal(await crypto.decryptWithAesGcmCombined(vector.ciphertext_b64, new Uint8Array(32).fill(42)), null);
      const tampered = Buffer.from(vector.ciphertext_b64, 'base64'); tampered[tampered.length - 1] ^= 1;
      assert.equal(await crypto.decryptWithAesGcmCombined(tampered.toString('base64'), key), null);
      if (tampered[0] === 0x4f && tampered[1] === 0x4d) {
        const header = Buffer.from(vector.ciphertext_b64, 'base64'); header[2] ^= 1;
        assert.equal(await crypto.decryptWithAesGcmCombined(header.toString('base64'), key), null);
      }
      results.push({ id: vector.id, status: 'passed' });
    }
  } else if (capability === 'crypto.recovery-envelope.v1') {
    const crypto = await import(source('crypto'));
    for (const vector of suite.vectors) {
      const keypair = await crypto.deriveChatCompletionRecoveryKeypair(vector.chat_key, vector.chat_id, vector.key_version);
      assert.equal(keypair.privateKey, vector.recovery_private_key); assert.equal(keypair.publicKey, vector.recovery_public_key);
      assert.equal(crypto.buildRecoveryAssociatedData(vector), vector.associated_data);
      const options = { recoveryPrivateKey: keypair.privateKey, ownerId: vector.owner_id, chatId: vector.chat_id, turnId: vector.turn_id, jobId: vector.job_id, assistantMessageId: vector.assistant_message_id, keyVersion: vector.key_version };
      assert.equal(Buffer.from(await crypto.openChatCompletionRecoveryEnvelope(vector.envelope, options)).toString('utf8'), vector.plaintext);
      await assert.rejects(() => crypto.openChatCompletionRecoveryEnvelope(vector.envelope, { ...options, keyVersion: options.keyVersion + 1 }));
      for (const field of ['epk', 'nonce', 'ciphertext']) {
        const raw = Buffer.from(vector.envelope[field], 'base64url'); raw[0] ^= 1;
        await assert.rejects(() => crypto.openChatCompletionRecoveryEnvelope({ ...vector.envelope, [field]: raw.toString('base64url') }, options));
      }
      await assert.rejects(() => crypto.openChatCompletionRecoveryEnvelope({ ...vector.envelope, epk: Buffer.alloc(32).toString('base64url') }, options));
      results.push({ id: vector.name, status: 'passed' });
    }
  } else if (capability === 'crypto.slug-lookup.v1') {
    const slugs = await import(source('objectSlugs'));
    for (const vector of suite.vectors) {
      const key = new Uint8Array(Buffer.from(vector.key_b64, 'base64'));
      const metadata = await slugs.buildEncryptedObjectSlugMetadata({ value: vector.input, encryptionKey: key, lookupKey: key });
      assert.equal(metadata.slug, vector.normalized); assert.equal(metadata.slug_lookup_hash, vector.lookup_hash);
      assert.throws(() => slugs.normalizeObjectSlug('❄'));
      results.push({ id: vector.id, status: 'passed' });
    }
  } else if (capability === 'protocol.generated-skills.v1') {
    generatedDiagnosticStage='sdk_import';
    const { OpenMates } = await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js', import.meta.url));
    generatedDiagnosticStage='vector_admission';
    for (const vector of suite.vectors) {
      generatedDiagnosticStage='vector_admission';
      generatedDiagnosticVector=vector&&typeof vector==='object'&&vector.id==='generated-web-search'?'generated-web-search':'none';
      const calls = []; const previous = globalThis.fetch;
      generatedDiagnosticStage='fetch_install';
      globalThis.fetch = async (input, init) => {
        const url = new URL(String(input)); calls.push({ method: init?.method, path: url.pathname, body: JSON.parse(init?.body), headers: new Headers(init?.headers) });
        return new Response(JSON.stringify(vector.response), { status: 200, headers: { 'content-type': 'application/json' } });
      };
      try {
        generatedDiagnosticStage='client_constructor';
        const client = new OpenMates({ apiKey: 'sk-api-synthetic-conformance.synthetic-local-setup-secret', apiUrl: 'https://api.example.invalid', deviceId: 'synthetic-conformance' });
        generatedDiagnosticStage='generated_dispatch';
        const output = await client.apps[vector.app][vector.skill](vector.input);
        generatedDiagnosticStage='response_assert';
        assert.deepEqual(output, vector.response);
        generatedDiagnosticStage='call_count_assert';
        assert.equal(calls.length, 1);
        generatedDiagnosticStage='method_assert';
        assert.equal(calls[0].method, vector.method);
        generatedDiagnosticStage='path_assert';
        assert.equal(calls[0].path, vector.path);
        generatedDiagnosticStage='body_assert';
        assert.deepEqual(calls[0].body, vector.input);
        generatedDiagnosticStage='authorization_assert';
        assert.equal(calls[0].headers.get('authorization'), 'Bearer sk-api-synthetic-conformance');
      } finally {
        const generatedBeforeRestore=generatedDiagnosticStage;
        generatedDiagnosticStage='fetch_restore';
        globalThis.fetch = previous;
        generatedDiagnosticStage=generatedBeforeRestore;
      }
      generatedDiagnosticStage='record_result';
      results.push({ id: vector.id, status: 'passed' });
      generatedDiagnosticVector='none';
    }
  } else if (capability === 'sdk.api-key-operations.v1') {
    const { runOperationVectors } = await import('./sdk-api-key-operations.mjs');
    results.push(...await runOperationVectors(suite, await import(source('sdk'))));
  } else if (capability === 'sdk.api-key-memories.v1') {
    const { runMemoryVectors } = await import('./sdk-api-key-operations.mjs');
    results.push(...await runMemoryVectors(suite, await import(source('crypto')), await import(source('sdkCrypto'))));
  } else if (capability === 'session.native-boundary.v1') {
    const { SessionClient, SessionClientError } = await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js', import.meta.url));
    for (const vector of suite.vectors) {
      const options = { apiUrl: vector.options.api_url, appUrl: vector.options.app_url, privacy: { enhanced: false }, allowPrivateOperations: false };
      const client = new SessionClient(options);
      const refused = code => error => error instanceof SessionClientError && error.code === code;
      try {
        await client.importSession(vector.session);
        assert.deepEqual((await client.exportSession({ includeSecrets: true })).session, vector.session);
        await assert.rejects(() => client.exportSession({ includeSecrets: false }), refused('forbidden'));
        await assert.rejects(() => client.importSession({ ...vector.session, api_url: 'https://other.example.invalid' }), refused('forbidden'));
        await assert.rejects(() => client.loginPassword('invalid', 'synthetic-private-password'), refused('authentication'));
        assert.deepEqual((await client.exportSession({ includeSecrets: true })).session, vector.session);
        assert.throws(() => new SessionClient({ ...options, privacy: { enhanced: true } }), refused('invalid_argument'));
        assert.throws(() => client.respondToConsent('invented', []), refused('forbidden'));
        await assert.rejects(() => client.send('Synthetic private send'), refused('forbidden'));
        client.cancel();
        await client.logout();
        await assert.rejects(() => client.exportSession({ includeSecrets: true }), refused('authentication'));
      } finally { await client.close(); }
      await assert.rejects(() => client.list('chats'), refused('cancelled'));
      results.push({ id: vector.id, status: 'passed' });
    }
  } else { throw new Error('Unsupported conformance capability'); }
  generatedDiagnosticStage='result_summary';
  assert.ok(results.length > 0);
  generatedDiagnosticStage='emit_result';
  process.stdout.write(JSON.stringify({ capability, language: 'npm', status: 'passed', fixtureSha256, results }) + '\n');
} catch (error) {
  process.stderr.write(`npm SDK conformance failed: ${capability ?? 'invalid arguments'}\n`);
  if(process.env.OPENMATES_SDK_CONFORMANCE_DEBUG)process.stderr.write(String(error?.stack??error)+'\n');
  process.exitCode = 1;
  if(capability==='protocol.generated-skills.v1'){
    try{process.stderr.write(generatedDiagnosticLine(generatedDiagnosticStage,generatedDiagnosticVector,generatedDiagnosticError(error)));}catch{}
  }
}
