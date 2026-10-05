/** Disposable encrypted Project writer through the normal authorized CLI tool path. */
import { randomBytes, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

let cryptoModule;
let slugModule;
function stageFailure(phase, error) {
  const failure = new Error(String(error?.message || error));
  failure.capacityPhase = phase;
  failure.capacityErrorClass = /^[A-Za-z][A-Za-z0-9]{0,63}$/.test(error?.name || '') ? error.name : 'Error';
  const ownFrame = new Error().stack?.split('\n').find(line =>
    line.includes('storage_capacity_version_adapter.mjs:') && !line.includes('stageFailure'));
  const ownLine = /storage_capacity_version_adapter\.mjs:(\d+):\d+/.exec(ownFrame || '');
  failure.capacitySourceLocation = ownLine ? `storage_capacity_version_adapter.mjs:${ownLine[1]}` :
    'storage_capacity_version_adapter.mjs:unavailable';
  return failure;
}

/** Only documented response states and bounded counts may cross the diagnostic boundary. */
export function sanitizeVersionDiagnostics(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result = {};
  if (new Set(['completed', 'waiting_for_user', 'missing', 'other']).has(value.response_status)) {
    result.response_status = value.response_status;
  }
  if (Number.isInteger(value.callback_count) && value.callback_count >= 0 && value.callback_count <= 1000) {
    result.callback_count = value.callback_count;
  }
  if (Number.isSafeInteger(value.expected_revision) && value.expected_revision >= 1 && value.expected_revision <= 1000000) {
    result.expected_revision = value.expected_revision;
  }
  return result;
}

/** Keep the independent ledger's exact equality gate and reveal only shape on failure. */
export function assertVersionReadback(fetched, expectedContent, expectedRevision) {
  const contentMatches = fetched?.content === expectedContent;
  const revisionMatches = fetched?.version_number === expectedRevision;
  if (contentMatches && revisionMatches) return;
  const actualRevision = fetched?.version_number;
  const detail = [
    `content_matches=${contentMatches}`,
    `revision_matches=${revisionMatches}`,
    `expected_revision=${expectedRevision}`,
    Number.isSafeInteger(actualRevision)
      ? `actual_revision=${actualRevision}`
      : `actual_revision_type=${typeof actualRevision}`,
  ];
  throw stageFailure('version_readback', new Error(`Client bounded version reconstruction mismatch: ${detail.join(' ')}`));
}
async function modules() {
  if (!cryptoModule) {
    const dist = resolve('frontend/packages/openmates-cli/dist/capacity-helpers');
    cryptoModule = await import(pathToFileURL(resolve(dist, 'crypto.js')).href);
    slugModule = await import(pathToFileURL(resolve(dist, 'objectSlugs.js')).href);
  }
  return { ...cryptoModule, ...slugModule };
}

export async function createCapacityProject(client, user) {
  const { encryptBytesWithAesGcm, encryptWithAesGcmCombined, buildEncryptedObjectSlugMetadata } = await modules();
  const { key: masterKey, teamId } = await client.projectWrappingKey({ personal: true });
  if (teamId !== null) throw new Error('Capacity Project must be personal and disposable');
  const projectKey = randomBytes(32);
  const projectId = randomUUID();
  const name = `Synthetic Capacity ${user}`;
  const focus = { focus_id: randomUUID(), name: `Work on ${name}`,
    instructions: 'Apply the explicitly requested synthetic capacity file edits in this disposable Project.',
    source: 'generated' };
  const slug = await buildEncryptedObjectSlugMetadata({ value: name, encryptionKey: projectKey, lookupKey: masterKey });
  const timestamp = Math.floor(Date.now() / 1000);
  const response = await client.createProject({
    project_id: projectId,
    encrypted_project_key: await encryptBytesWithAesGcm(projectKey, masterKey),
    encrypted_slug: slug.encrypted_slug,
    slug_lookup_hash: slug.slug_lookup_hash,
    encrypted_name: await encryptWithAesGcmCombined(name, projectKey),
    encrypted_description: await encryptWithAesGcmCombined('', projectKey),
    encrypted_icon: await encryptWithAesGcmCombined('folder', projectKey),
    encrypted_color: await encryptWithAesGcmCombined('default', projectKey),
    pinned: false,
    created_at: timestamp, updated_at: timestamp, last_opened_at: timestamp,
    write_mode: 'always_ask',
    default_focus_id: focus.focus_id,
    encrypted_settings: await encryptWithAesGcmCombined(JSON.stringify({ default_focus: focus }), projectKey),
    key_wrappers: [],
  }, { personal: true });
  if (response?.project?.project_id !== projectId) throw new Error('Encrypted Project creation was not acknowledged');
  return { projectId, currentContent: null, embedId: null, revision: 0 };
}

export async function writeVersion({ client, chatId, project, content }) {
  if (!project?.projectId) throw new Error('No authorized disposable Project');
  const creating = project.revision === 0;
  const old = project.currentContent;
  if (!creating && typeof old !== 'string') throw new Error('Previous Project content is unavailable');
  const scenario = creating ? 'version_create' : 'version_update';
  const prompt = [
    `STORAGE_CAPACITY_SCENARIO:${scenario}`,
    `CAPACITY_VERSION_NEW:${content}`,
    ...(creating ? [] : [`CAPACITY_VERSION_OLD:${old}`]),
    'Use the Project file tool on capacity.txt and confirm the result.',
  ].join('\n');
  const committed = [];
  let response;
  try {
    response = await client.sendMessage({
      message: prompt, chatId, projectId: project.projectId,
      testMockMarker: '<<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
      onProjectWriteApproval: async () => true,
      onHostedVersionCommitted: (value) => committed.push(value),
    });
  } catch (error) {
    throw stageFailure('version_send', error);
  }
  if (response?.status !== 'completed' || committed.length !== 1) {
    const failure = stageFailure('version_callback_count', new Error('Authorized Project tool did not commit exactly one version'));
    failure.capacityDiagnostics = sanitizeVersionDiagnostics({
      response_status: response?.status == null ? 'missing' :
        ['completed', 'waiting_for_user'].includes(response.status) ? response.status : 'other',
      callback_count: Math.min(committed.length, 1000),
      expected_revision: project.revision + 1,
    });
    throw failure;
  }
  const { embed_id: embedId, revision } = committed[0];
  if (!embedId || !Number.isInteger(revision) || revision !== project.revision + 1 ||
      (project.embedId && embedId !== project.embedId)) {
    throw stageFailure('version_callback_count', new Error('Project version identity/revision mismatch'));
  }
  let fetched;
  try {
    fetched = await client.getEmbedVersion(embedId, revision, { projectId: project.projectId });
  } catch (error) {
    throw stageFailure('version_readback', error);
  }
  assertVersionReadback(fetched, content, revision);
  project.embedId = embedId;
  project.revision = revision;
  project.currentContent = content;
  return { persisted: true, reconstructedContent: fetched.content, embedId, revision };
}
