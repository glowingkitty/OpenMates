/** Encrypted authoring receipts and exact manual proposal grants. */
// contract-test-file: supporting surface=cli assertions=focus-modes.project-authoring-persistence,focus-modes.project-authoring-click
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { persistCliProjectAuthoringJob, AuthoringSaveApprovalRequired, authoringReplacementPatch } from '../src/cliProjectAuthoringSave.ts';
import { projectItemRevision } from '../src/cliProjectAuthoring.ts';
import { encryptWithAesGcmCombined, decryptWithAesGcmCombined, decryptBytesWithAesGcm } from '../src/crypto.ts';
import { applyProjectFilePatch } from '../../ui/src/utils/projectFilePatch.ts';

const key = new Uint8Array(32).fill(4), chatKey = new Uint8Array(32).fill(6);
const markdown = '---\nname: Project specialist\ndescription: Useful guidance\nwhen_to_use: Project changes\n---\nUse the actual Project goals.\n';
function draftJob() { return { job_id: 'job', project_id: 'project', chat_id: 'chat', team_id: null, kind: 'focus', action: 'create', status: 'needs_save', result_id: 'result', expected_revision: null,
  draft: { save_operation_id: 'project-authoring:job', path: '.openmates/focuses/result/SKILL.md', expected_embed_revision: 0, markdown,
    document: { name: 'Project specialist', description: 'Useful guidance', when_to_use: 'Project changes' } } }; }
async function fixture(mode: 'apply_and_show' | 'always_ask' = 'apply_and_show') {
  const items: Array<Record<string, unknown>> = [], payloads: Array<Record<string, unknown>> = [], acknowledgements: Array<Record<string, unknown>> = [], approvals: Array<Record<string, unknown>> = [];
  let committedDigest: string | null = null;
  const client = {
    async getActiveProjectFocus() { return { project_id: 'project', team_id: null, focus_id: 'accepted' }; },
    async getProject() { return { project: {}, items, folders: [] }; },
    async decryptProjectKey() { return key; },
    async getProjectSettings() { return { write_mode: mode, selection_required: false, encrypted_settings: await encryptWithAesGcmCombined('{}', key) }; },
    async getChatEncryptionKey() { return chatKey; },
    async readEncryptedProjectFile() { throw new Error('must not read unrelated private files'); },
    async getProjectFileRevisionReceipt(_project: string, _embed: string, _operation: string, _chat: string, digest: string) { return committedDigest === digest ? { status: 'committed', current_revision: 1 } : null; },
    async approveProjectWrite(_project: string, input: Record<string, unknown>) { approvals.push(input); },
    async commitHostedProjectFileRevision(payload: Record<string, unknown>) {
      payloads.push(payload); const create = payload.create as Record<string, unknown>;
      assert.equal(create.project_item_id, 'result'); assert.equal(payload.expected_revision, 0);
      committedDigest = String(payload.proposal_digest);
      items.push({ project_item_id: 'result', item_type: 'embed', target_id_encrypted: create.target_id_encrypted,
        encrypted_metadata: create.encrypted_metadata, updated_at: 1, target_id_hash: 'hash' });
      return { status: 'committed', current_revision: 1 };
    },
    async acknowledgeProjectAuthoringSave(_project: string, _job: string, _kind: string, input: Record<string, unknown>) {
      acknowledgements.push(input); assert.equal(input.saved_revision, projectItemRevision(items[0]));
      return { job_id: 'job', status: 'ready' };
    },
  };
  return { client, items, payloads, acknowledgements, approvals };
}

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('commits encrypted Focus head/history/metadata and marks ready only after its receipt-bound saved acknowledgement', async () => {
  const f = await fixture(); const result = await persistCliProjectAuthoringJob(f.client as never, draftJob());
  assert.equal(result.status, 'ready'); assert.equal(f.payloads.length, 1); assert.equal(f.acknowledgements.length, 1);
  assert.equal(f.approvals.length, 0); assert.doesNotMatch(JSON.stringify(f.payloads), /actual Project goals|Useful guidance/);
  const create = f.payloads[0].create as Record<string, unknown>;
  const metadata = JSON.parse((await decryptWithAesGcmCombined(String(create.encrypted_metadata), key))!);
  assert.equal(metadata.focus_title, 'Project specialist'); assert.equal(metadata.display_path, '.openmates/focuses/result/SKILL.md');
  const wrappers = create.key_wrappers as Array<Record<string, unknown>>;
  const embedKey = await decryptBytesWithAesGcm(String(wrappers.find(row => row.key_type === 'project')!.encrypted_embed_key), key);
  assert.equal(await decryptWithAesGcmCombined(String((f.payloads[0].history_rows as Array<Record<string, unknown>>)[0].encrypted_snapshot), embedKey!), markdown);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence,focus-modes.project-authoring-click
it('always_ask requires a user action approving the generated exact digest and does not treat generation as write approval', async () => {
  const f = await fixture('always_ask'); const job = draftJob(); let proposal: AuthoringSaveApprovalRequired | undefined;
  await assert.rejects(persistCliProjectAuthoringJob(f.client as never, job), error => { assert.ok(error instanceof AuthoringSaveApprovalRequired); proposal = error; return true; });
  assert.equal(f.payloads.length, 0); assert.equal(f.approvals.length, 0);
  const changed = { ...job, draft: { ...job.draft, markdown: markdown + 'Changed private proposal.\n' } };
  await assert.rejects(persistCliProjectAuthoringJob(f.client as never, changed, proposal!.digest), AuthoringSaveApprovalRequired);
  assert.equal(f.approvals.length, 0);
  await persistCliProjectAuthoringJob(f.client as never, job, proposal!.digest);
  assert.equal(f.approvals.length, 1); assert.equal(f.approvals[0].proposal_digest, proposal!.digest);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('retries a completed create through its exact receipt without a second write or manual approval', async () => {
  const f = await fixture('always_ask'); const job = draftJob(); let digest = '';
  try { await persistCliProjectAuthoringJob(f.client as never, job); } catch (error) { assert.ok(error instanceof AuthoringSaveApprovalRequired); digest = error.digest; }
  await persistCliProjectAuthoringJob(f.client as never, job, digest);
  await persistCliProjectAuthoringJob(f.client as never, job);
  assert.equal(f.payloads.length, 1); assert.equal(f.approvals.length, 1); assert.equal(f.acknowledgements.length, 2);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('rejects stale Project focus and a mismatched save identity before committing or acknowledging', async () => {
  const f = await fixture(); f.client.getActiveProjectFocus = async () => ({ project_id: 'other', team_id: null, focus_id: 'other' });
  await assert.rejects(persistCliProjectAuthoringJob(f.client as never, draftJob()), /no longer active/);
  assert.equal(f.payloads.length, 0); assert.equal(f.acknowledgements.length, 0);
  const fresh = await fixture(); const job = draftJob(); job.draft.save_operation_id = 'unrelated';
  await assert.rejects(persistCliProjectAuthoringJob(fresh.client as never, job), /identity/);
  assert.equal(fresh.payloads.length, 0);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('does not acknowledge rejected transactions or overwrite a protected Focus path', async () => {
  const f = await fixture(); f.client.commitHostedProjectFileRevision = async () => ({ status: 'conflict', current_revision: 2 });
  await assert.rejects(persistCliProjectAuthoringJob(f.client as never, draftJob()), /revision_conflict/);
  assert.equal(f.acknowledgements.length, 0);
  const protectedFile = await fixture(); protectedFile.client.getProjectSettings = async () => ({ write_mode: 'apply_and_show', selection_required: false,
    encrypted_settings: await encryptWithAesGcmCombined(JSON.stringify({ file_access: { private_paths: ['.openmates/focuses/**'] } }), key) });
  await assert.rejects(persistCliProjectAuthoringJob(protectedFile.client as never, draftJob()), /protected_path/);
  assert.equal(protectedFile.payloads.length, 0); assert.equal(protectedFile.acknowledgements.length, 0);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('exact replacement patches preserve all combinations of final newlines, including empty files', () => {
  for (const original of ['', 'old', 'old\n', 'old\nline']) for (const content of ['', 'new', 'new\n', 'new\nline']) {
    assert.equal(applyProjectFilePatch(original, authoringReplacementPatch('file.md', original, content), 'file.md').content, content);
  }
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('persists Workflow binding metadata only after source completion and acknowledges the updated item revision', async () => {
  const f = await fixture(); f.items.push({ project_item_id: 'linked-workflow', item_type: 'workflow', updated_at: 1,
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({ keep: 'metadata' }), key) });
  const job = { job_id: 'job', chat_id: 'chat', project_id: 'project', team_id: null, kind: 'workflow', status: 'pending_file',
    project_item_id: 'linked-workflow', expected_item_revision: projectItemRevision(f.items[0]), workflow_version_id: 'version',
    draft: { remote_binding: { project_id: 'project', source_id: 'source', workflow_version_id: 'version', file_path: 'workflow.yml', base_hash: 'verified' } } };
  let writes = 0;
  const client = { ...f.client, async updateProjectItemMetadata(_project: string, id: string, ciphertext: string, _options: unknown, revision: string) {
    writes++; assert.equal(id, 'linked-workflow'); assert.equal(revision, job.expected_item_revision);
    const metadata = JSON.parse((await decryptWithAesGcmCombined(ciphertext, key))!);
    assert.equal(metadata.keep, 'metadata'); assert.equal(metadata.remote_file_status, 'saved');
    f.items[0].encrypted_metadata = ciphertext;
  }, async acknowledgeProjectAuthoringSave(_project: string, _job: string, kind: string, input: Record<string, unknown>) {
    assert.equal(kind, 'workflow'); assert.equal(input.saved_item_revision, projectItemRevision(f.items[0]));
    return { job_id: 'job', status: 'ready' };
  } };
  assert.equal((await persistCliProjectAuthoringJob(client as never, job)).status, 'pending_file'); assert.equal(writes, 0);
  assert.equal((await persistCliProjectAuthoringJob(client as never, { ...job, status: 'needs_binding_save' })).status, 'ready'); assert.equal(writes, 1);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('updates an exact Focus item/head revision, then retries its receipt without applying a second patch', async () => {
  const f = await fixture();
  f.items.push({ project_item_id: 'result', item_type: 'embed', updated_at: 1, target_id_encrypted: await encryptWithAesGcmCombined('existing-embed', key),
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({ path: '.openmates/focuses/result/SKILL.md', keep: 'existing' }), key) });
  const job = { ...draftJob(), action: 'update', expected_revision: projectItemRevision(f.items[0]), draft: { ...draftJob().draft, expected_embed_revision: 1 } };
  const original = 'Old Focus content.\n'; let headRevision = 1, committedDigest = '', writes = 0, metadataWrites = 0;
  const client = { ...f.client,
    async readEncryptedProjectFile() { return { revision: headRevision, embedKey: key, content: { code: headRevision === 1 ? original : markdown }, hasInitialHistory: true }; },
    async getEmbedVersion() { return { content: original }; },
    async getProjectFileRevisionReceipt(_project: string, _embed: string, _operation: string, _chat: string, digest: string) { return committedDigest === digest ? { status: 'committed', current_revision: 2 } : null; },
    async commitHostedProjectFileRevision(payload: Record<string, unknown>) {
      writes++; assert.equal(payload.expected_revision, 1); assert.equal(payload.embed_id, 'existing-embed'); assert.equal(payload.create, undefined);
      const patch = (payload.history_rows as Array<Record<string, unknown>>)[0];
      assert.equal(applyProjectFilePatch(original, (await decryptWithAesGcmCombined(String(patch.encrypted_patch), key))!, '.openmates/focuses/result/SKILL.md').content, markdown);
      headRevision = 2; committedDigest = String(payload.proposal_digest); return { status: 'committed', current_revision: 2 };
    },
    async updateProjectItemMetadata(_project: string, _id: string, ciphertext: string, _options: unknown, expected: string) {
      metadataWrites++; assert.equal(expected, job.expected_revision);
      f.items[0].encrypted_metadata = ciphertext;
      assert.equal(JSON.parse((await decryptWithAesGcmCombined(ciphertext, key))!).keep, 'existing');
    },
  };
  await persistCliProjectAuthoringJob(client as never, job); await persistCliProjectAuthoringJob(client as never, job);
  assert.equal(writes, 1); assert.equal(metadataWrites, 1); assert.equal(f.acknowledgements.length, 2);
  headRevision = 3;
  await assert.rejects(persistCliProjectAuthoringJob(client as never, job), /head changed/);
  assert.equal(writes, 1); assert.equal(f.acknowledgements.length, 2);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence,focus-modes.project-authoring-click
it('reviews an Update after only the typed pre-approval receipt denial, then commits on exact Save', async () => {
  const f = await fixture('always_ask');
  f.items.push({ project_item_id: 'result', item_type: 'embed', updated_at: 1,
    target_id_encrypted: await encryptWithAesGcmCombined('existing-embed', key),
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({ path: '.openmates/focuses/result/SKILL.md' }), key) });
  const job = { ...draftJob(), action: 'update', expected_revision: projectItemRevision(f.items[0]),
    draft: { ...draftJob().draft, expected_embed_revision: 1 } };
  let approved = false, committed = false, writes = 0, acknowledgements = 0;
  const denial = (code: string) => Object.assign(new Error(code), { code, status: 409 });
  const client = { ...f.client,
    async readEncryptedProjectFile() { return { revision: 1, embedKey: key, content: { code: 'Old Focus content.\n' }, hasInitialHistory: true }; },
    async getProjectFileRevisionReceipt() {
      if (!approved) throw denial('PROJECT_WRITE_APPROVAL_REQUIRED');
      return committed ? { status: 'committed', current_revision: 2 } : null;
    },
    async approveProjectWrite(_project: string, input: Record<string, unknown>) {
      assert.equal(input.operation_id, job.draft.save_operation_id); approved = true;
    },
    async commitHostedProjectFileRevision(payload: Record<string, unknown>) {
      writes++; assert.equal(payload.expected_revision, 1); committed = true;
      return { status: 'committed', current_revision: 2 };
    },
    async updateProjectItemMetadata(_project: string, _id: string, ciphertext: string) {
      f.items[0].encrypted_metadata = ciphertext;
      f.items[0].updated_at = 2;
    },
    async acknowledgeProjectAuthoringSave() { acknowledgements++; return { status: 'ready' }; },
  };
  let proposal: AuthoringSaveApprovalRequired | undefined;
  await assert.rejects(persistCliProjectAuthoringJob(client as never, job), error => {
    assert.ok(error instanceof AuthoringSaveApprovalRequired); proposal = error; return true;
  });
  assert.equal(approved, false); assert.equal(writes, 0); assert.equal(acknowledgements, 0);
  assert.equal((await persistCliProjectAuthoringJob(client as never, job, proposal!.digest)).status, 'ready');
  assert.equal(approved, true); assert.equal(writes, 1); assert.equal(acknowledgements, 1);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-persistence
it('does not treat an unrelated receipt 409 as Save approval or acknowledge it', async () => {
  const f = await fixture('always_ask');
  let approvals = 0, acknowledgements = 0;
  const client = { ...f.client,
    async getProjectFileRevisionReceipt() {
      throw Object.assign(new Error('PROJECT_WRITE_APPROVAL_MISMATCH'),
        { code: 'PROJECT_WRITE_APPROVAL_MISMATCH', status: 409 });
    },
    async approveProjectWrite() { approvals++; },
    async acknowledgeProjectAuthoringSave() { acknowledgements++; return { status: 'ready' }; },
  };
  await assert.rejects(persistCliProjectAuthoringJob(client as never, draftJob()),
    /PROJECT_WRITE_APPROVAL_MISMATCH/);
  assert.equal(approvals, 0); assert.equal(acknowledgements, 0);
});
