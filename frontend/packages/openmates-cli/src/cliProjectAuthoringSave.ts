/** Durable encrypted authoring saves use the ordinary hosted-file CAS transaction. */
import type { OpenMatesClient } from './client.js';
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined, encryptBytesWithAesGcm } from './crypto.js';
import { toonEncodeContent } from './embedCreator.js';
import { projectItemRevision } from './cliProjectAuthoring.js';
import { projectPrivatePaths } from './projectFileExecutor.js';
import { executeHostedProjectFileJob, hostedProjectFileIdentity, normalizeHostedProjectPath, projectFileContentHash, type HostedProjectFile } from '../../ui/src/services/hostedProjectFileExecutor.js';
import { projectFileMutationDigest, type ProjectFileMutation } from '../../ui/src/utils/projectFileMutationProtocol.js';
import type { ProjectFileJob } from '../../ui/src/services/projectFileJobExecutor.js';

export class AuthoringSaveApprovalRequired extends Error {
  readonly digest: string;
  readonly mutation: ProjectFileMutation;
  constructor(digest: string, mutation: ProjectFileMutation) { super('Review the generated file, then choose Save to approve this exact write.'); this.digest = digest; this.mutation = mutation; }
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Authoring response is incomplete.');
  return value as Record<string, unknown>;
}
function sameObject(left: unknown, right: unknown): boolean {
  const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical)
    : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([name, child]) => [name, canonical(child)])) : value;
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}
function required(value: unknown): string { if (typeof value !== 'string' || !value) throw new Error('Authoring response is incomplete.'); return value; }
/** Full replacement with exact line counts and final-newline markers. */
export function authoringReplacementPatch(path: string, original: string, content: string): string {
  const lines = (text: string, prefix: string) => {
    if (!text) return { count: 0, rows: [] as string[] };
    const parts = text.split('\n'); const newline = parts.at(-1) === ''; if (newline) parts.pop();
    const rows = parts.map(line => prefix + line); if (!newline) rows.push('\\ No newline at end of file');
    return { count: parts.length, rows };
  };
  const old = lines(original, '-'), next = lines(content, '+');
  return [`--- a/${path}`, `+++ b/${path}`, `@@ -${old.count ? 1 : 0},${old.count} +${next.count ? 1 : 0},${next.count} @@`, ...old.rows, ...next.rows, ''].join('\n');
}

export async function persistCliProjectAuthoringJob(client: OpenMatesClient, job: Record<string, unknown>, approvedDigest?: string): Promise<Record<string, unknown>> {
  if (!['needs_save', 'needs_binding_save'].includes(String(job.status))) return job;
  const projectId = required(job.project_id), chatId = required(job.chat_id), jobId = required(job.job_id);
  const active = await client.getActiveProjectFocus(chatId);
  if (active?.project_id !== projectId || active.team_id !== (job.team_id ?? null)) throw new Error('This Project Focus is no longer active.');
  const options = { teamId: active.team_id, personal: !active.team_id };
  const detail = await client.getProject(projectId, options);
  const projectKey = await client.decryptProjectKey(detail.project, options);
  const draft = record(job.draft);
  const fresh = async () => {
    const focus = await client.getActiveProjectFocus(chatId);
    if (focus?.project_id !== projectId || focus.team_id !== active.team_id || focus.focus_id !== active.focus_id || focus.activated_at !== active.activated_at) throw new Error('This Project Focus is no longer active.');
  };
  if (job.status === 'needs_binding_save') {
    const id = required(job.project_item_id), binding = record(draft.remote_binding);
    if (binding.project_id !== projectId || binding.workflow_version_id !== job.workflow_version_id) throw new Error('Workflow file binding does not match the completed job.');
    const item = detail.items.find(row => row.project_item_id === id && row.item_type === 'workflow' && !row.deleted_target_state);
    if (!item) throw new Error('The linked Workflow is unavailable.');
    const metadata = item.encrypted_metadata ? record(JSON.parse(required(await decryptWithAesGcmCombined(item.encrypted_metadata, projectKey)))) : {};
    const alreadySaved = metadata.authoring_save_operation === `project-authoring:${jobId}` && metadata.remote_file_status === "saved" && sameObject(metadata.remote_workflow_file, binding);
    if (projectItemRevision(item) !== job.expected_item_revision && !alreadySaved) throw new Error('The Workflow link changed. Refresh the recommendation.');
    if (!alreadySaved) {
      await fresh();
      await client.updateProjectItemMetadata(projectId, id, await encryptWithAesGcmCombined(JSON.stringify({ ...metadata,
        remote_workflow_file: binding, remote_file_status: 'saved', authoring_save_operation: `project-authoring:${jobId}` }), projectKey), options, projectItemRevision(item));
    }
    const saved = (await client.getProject(projectId, options)).items.find(row => row.project_item_id === id);
    if (!saved) throw new Error('The saved Workflow link is unavailable.');
    return client.acknowledgeProjectAuthoringSave(projectId, jobId, 'workflow', { project_item_id: id,
      saved_item_revision: projectItemRevision(saved), workflow_version_id: required(job.workflow_version_id) });
  }
  const operationId = required(draft.save_operation_id);
  if (operationId !== `project-authoring:${jobId}`) throw new Error('Authoring save identity does not match the job.');
  const id = required(job.result_id), document = record(draft.document), markdown = required(draft.markdown);
  if (markdown.length > 200_000 || markdown.includes('\r') || markdown.includes('\0')) throw new Error('The Focus draft is not a supported file.');
  const expectedHead = Number(draft.expected_embed_revision);
  if (!Number.isSafeInteger(expectedHead) || expectedHead < 0) throw new Error('The Focus base revision is unavailable.');
  const item = detail.items.find(row => row.project_item_id === id && row.item_type === 'embed' && !row.deleted_target_state);
  const metadata = item?.encrypted_metadata ? record(JSON.parse(required(await decryptWithAesGcmCombined(item.encrypted_metadata, projectKey)))) : {};
  if (job.action === 'update' && (!item || (projectItemRevision(item) !== job.expected_revision && metadata.authoring_save_operation !== operationId))) throw new Error('The selected Focus changed. Refresh the recommendation.');
  if (job.action === 'create' && item && metadata.authoring_save_operation !== operationId) throw new Error('The Focus identity is already in use.');
  const path = normalizeHostedProjectPath(job.action === 'update' ? metadata.path ?? metadata.display_path : draft.path);
  if (!/^\.openmates\/focuses\/[^\0]+(?:\.md|\/SKILL\.md)$/.test(path)) throw new Error('The Focus save path is invalid.');
  const embedId = item ? required(await decryptWithAesGcmCombined(item.target_id_encrypted, projectKey)) : await hostedProjectFileIdentity(projectKey, path, 'embed');
  const [settings, chatKey] = await Promise.all([client.getProjectSettings(projectId, options), client.getChatEncryptionKey(chatId, options)]);
  if (settings.selection_required || !['apply_and_show', 'always_ask'].includes(String(settings.write_mode))) throw new Error('Choose this Project’s write policy before saving.');
  const settingsText = settings.encrypted_settings ? await decryptWithAesGcmCombined(settings.encrypted_settings, projectKey) : null;
  if (settings.encrypted_settings && !settingsText) throw new Error('The Project write settings are unavailable.');
  let original = '';
  if (expectedHead) {
    const head = await client.readEncryptedProjectFile(projectId, embedId, projectKey, options);
    if (head.revision !== expectedHead && head.revision !== expectedHead + 1) throw new Error('The Focus head changed. Refresh the recommendation.');
    original = head.revision === expectedHead ? required(head.content.code ?? head.content.content)
      : required((await client.getEmbedVersion(embedId, expectedHead, { projectId, teamId: active.team_id ?? undefined })).content);
  }
  const mutation: ProjectFileMutation = expectedHead ? { operation: 'update_file', operation_id: operationId, path,
    expected_base: await projectFileContentHash(original), patch: authoringReplacementPatch(path, original, markdown) }
    : { operation: 'create_file', operation_id: operationId, path, expected_base: null, content: markdown };
  const digest = await projectFileMutationDigest(projectKey, projectId, chatId, mutation);
  const receipt = await client.getProjectFileRevisionReceipt(projectId, embedId, operationId, chatId, digest, options);
  if (receipt?.status !== 'committed' && settings.write_mode === 'always_ask') {
    if (approvedDigest !== digest) throw new AuthoringSaveApprovalRequired(digest, mutation);
    await fresh();
    await client.approveProjectWrite(projectId, { chat_id: chatId, operation_id: operationId, proposal_digest: digest }, options);
  }
  const focusMetadata = { ...metadata, path, display_path: path, source: 'hosted_project_file', focus_title: required(document.name),
    focus_description: required(document.description), focus_when_to_use: required(document.when_to_use), authoring_save_operation: operationId };
  const files: HostedProjectFile[] = [];
  for (const row of detail.items) {
    if (!['embed', 'upload'].includes(row.item_type) || row.deleted_target_state) continue;
    const target = await decryptWithAesGcmCombined(row.target_id_encrypted, projectKey);
    const text = row.encrypted_metadata ? await decryptWithAesGcmCombined(row.encrypted_metadata, projectKey) : null;
    const meta = text ? record(JSON.parse(text)) : {};
    const filePath = meta.path ?? meta.file_path ?? meta.filename ?? meta.display_path;
    if (target && typeof filePath === 'string') files.push({ embedId: target, path: filePath });
  }
  // Adapter-only execution descriptor. No lease is claimed or source job is accepted here;
  // server commit independently enforces the authenticated Project focus/write policy.
  const descriptor: ProjectFileJob = { protocol_version: 1, operation_id: operationId, chat_id: chatId, project_id: projectId,
    operation: mutation.operation, arguments: { path }, lease_token: '', lease_generation: 0, lease_expires_at: 0 };
  await executeHostedProjectFileJob({ projectId, projectKey, chatKey, teamId: active.team_id,
    privatePaths: projectPrivatePaths(settingsText), encrypt: encryptWithAesGcmCombined, wrap: encryptBytesWithAesGcm,
    encodeContent: async content => toonEncodeContent(content), listFiles: async () => files,
    readHead: target => client.readEncryptedProjectFile(projectId, target, projectKey, options),
    receipt: (target, request, commitment) => client.getProjectFileRevisionReceipt(projectId, target, request.operation_id, chatId, commitment, options),
    commit: async payload => {
      await fresh();
      if (payload.expected_revision !== expectedHead) throw new Error('The Focus head changed.');
      if (payload.create) payload.create = { ...record(payload.create), project_item_id: id,
        encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify(focusMetadata), projectKey) };
      return client.commitHostedProjectFileRevision(payload);
    },
  }, descriptor, mutation);
  if (item && metadata.authoring_save_operation !== operationId) {
    await fresh();
    await client.updateProjectItemMetadata(projectId, id, await encryptWithAesGcmCombined(JSON.stringify(focusMetadata), projectKey), options, projectItemRevision(item));
  }
  const saved = (await client.getProject(projectId, options)).items.find(row => row.project_item_id === id);
  if (!saved) throw new Error('The saved Focus is unavailable.');
  await fresh();
  return client.acknowledgeProjectAuthoringSave(projectId, jobId, 'focus', { save_operation_id: operationId,
    project_item_id: id, embed_id: embedId, saved_revision: projectItemRevision(saved), expected_revision: job.expected_revision ?? null });
}
