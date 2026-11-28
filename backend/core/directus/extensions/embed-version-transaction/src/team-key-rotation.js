/* Internal transaction for the opaque key set published after a Team removal.
 * The Team row is locked through commit so an epoch is never published with
 * only some of its member or Project wrappers. */
import { randomUUID } from 'node:crypto';
import { ProtocolError } from './operations.js';

const TEAM_ROTATION_ROLES = new Set(['owner', 'admin']);
const LIVE_REVISION_TYPES = new Set(['docs/document', 'sheets/sheet', 'slides/deck', 'code/code']);
const HASH = /^[0-9a-f]{64}$/;
const REVISION_PREFIX = 'OMRV1.';
const TEAM_PROFILE_FIELDS = ['encrypted_name', 'encrypted_description', 'encrypted_profile_image_metadata'];
const reject = (status, code) => { throw new ProtocolError(status, code); };

function revisionEpoch(ciphertext) {
  if (typeof ciphertext !== 'string' || !ciphertext.startsWith(REVISION_PREFIX)) return null;
  const separator = ciphertext.indexOf('.', REVISION_PREFIX.length);
  if (separator < 0) reject(400, 'invalid_revision_ciphertext');
  const epoch = ciphertext.slice(REVISION_PREFIX.length, separator);
  const payload = ciphertext.slice(separator + 1);
  if (!/^[1-9][0-9]{0,9}$/.test(epoch) || Number(epoch) < 2 || Number(epoch) > 2147483647
      || payload.length < 40 || payload.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(payload)) {
    reject(400, 'invalid_revision_ciphertext');
  }
  return Number(epoch);
}

export function isLiveRevisionType(embed) {
  return LIVE_REVISION_TYPES.has(`${embed.app_id}/${embed.skill_id}`);
}

export function requireLegacyRevisionAllowed(team, embed) {
  if (revisionEpoch(embed.encrypted_content) !== null
    || (isLiveRevisionType(embed) && (team?.rotation_pending || team?.team_key_epoch > 1))) {
    reject(409, 'team_key_epoch_conflict');
  }
}

/** Compare an opaque revision's declared epoch with the locked Team row.
 * Personal and legacy rows remain readable. A revision that has entered the
 * epoch format can never return to unversioned ciphertext. Clients authenticate
 * the payload and its field, item and revision when opening it. */
export function requireRevisionCipherEpoch(team, currentCiphertext, nextCiphertexts, affected = false) {
  const currentEpoch = revisionEpoch(currentCiphertext);
  const nextEpochs = nextCiphertexts.filter((value) => value != null).map(revisionEpoch);
  if (!(affected && team?.team_key_epoch > 1)
    && currentEpoch === null && nextEpochs.every((epoch) => epoch === null)) return false;
  if (!team || currentEpoch > team.team_key_epoch
    || nextEpochs.some((epoch) => epoch === null || epoch !== team.team_key_epoch)) {
    reject(409, 'team_key_epoch_conflict');
  }
  return true;
}

function cipherMap(rows, identityField, cipherField, maxRows) {
  if (!Array.isArray(rows) || rows.length > maxRows) reject(400, 'invalid_rotation_upload');
  const byIdentity = new Map();
  for (const row of rows) {
    const identity = row?.[identityField];
    const cipher = row?.[cipherField];
    if (typeof identity !== 'string' || !HASH.test(identity) || byIdentity.has(identity)
        || typeof cipher !== 'string' || !cipher || cipher.length > 8192) {
      reject(400, 'invalid_rotation_upload');
    }
    byIdentity.set(identity, cipher);
  }
  return byIdentity;
}

function requireCoverage(keys, identities, code) {
  const expected = new Set(identities);
  if (keys.size !== expected.size || [...expected].some((identity) => !keys.has(identity))) reject(409, code);
}

function rotatedProfile(team, profile) {
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) {
    reject(400, 'invalid_team_profile_rotation');
  }
  const expected = TEAM_PROFILE_FIELDS.filter((field) => team[field]);
  if (Object.keys(profile).length !== expected.length) reject(409, 'team_profile_changed');
  return Object.fromEntries(expected.map((field) => {
    const entry = profile[field];
    if (entry?.before !== team[field]) reject(409, 'team_profile_changed');
    if (typeof entry.after !== 'string' || !entry.after || entry.after.length > 65536) {
      reject(400, 'invalid_team_profile_rotation');
    }
    return [field, entry.after];
  }));
}

export async function removeTeamMember(database, body) {
  const { team_hash: teamHash, actor_user_hash: actorHash, target_user_hash: targetHash,
    removed_at: removedAt } = body ?? {};
  if (![teamHash, actorHash, targetHash].every((hash) => typeof hash === 'string' && HASH.test(hash))
      || !Number.isInteger(removedAt) || removedAt < 0 || removedAt > 2147483647) {
    reject(400, 'invalid_team_member_removal');
  }
  return database.transaction(async (trx) => {
    const team = await trx('teams').where({ hashed_team_id: teamHash, status: 'active' }).forUpdate().first();
    if (!team) reject(403, 'team_permission_denied');
    const activeMembership = { hashed_team_id: teamHash, status: 'active' };
    const actor = await trx('team_memberships').where({
      ...activeMembership, hashed_user_id: actorHash,
    }).forShare().first();
    if (!actor || !TEAM_ROTATION_ROLES.has(actor.role)) reject(403, 'team_permission_denied');
    const target = await trx('team_memberships').where({
      ...activeMembership, hashed_user_id: targetHash,
    }).forUpdate().first();
    if (!target || target.role === 'owner') reject(404, 'team_member_not_found');

    await trx('team_memberships').where({ id: target.id }).update({
      status: 'removed', removed_at: removedAt, updated_at: removedAt,
    });
    await trx('team_key_wrappers').where({ hashed_team_id: teamHash, hashed_user_id: targetHash }).del();
    await trx('teams').where({ id: team.id }).update({ rotation_pending: true, updated_at: removedAt });
    return { removed: true };
  });
}

export async function applyTeamKeyRotation(database, body) {
  const { team_hash: teamHash, actor_user_hash: actorHash, team_key_epoch: epoch,
    encrypted_previous_team_keys: previous } = body ?? {};
  if (typeof teamHash !== 'string' || !HASH.test(teamHash)
      || typeof actorHash !== 'string' || !HASH.test(actorHash)
      || !Number.isInteger(epoch) || epoch < 2 || epoch > 2147483647
      || typeof previous !== 'string' || !previous || previous.length > 65536) {
    reject(400, 'invalid_rotation_upload');
  }
  const memberWrappers = cipherMap(body.wrappers, 'hashed_user_id', 'encrypted_team_key', 2000);
  const projectWrappers = cipherMap(body.project_key_wrappers, 'hashed_project_id', 'encrypted_project_key', 20000);

  return database.transaction(async (trx) => {
    const team = await trx('teams').where({ hashed_team_id: teamHash, status: 'active' }).forUpdate().first();
    if (!team) reject(403, 'team_permission_denied');
    // Recheck membership under row locks. A member removal that won the
    // membership update cannot appear in a key set committed after it.
    const members = await trx('team_memberships')
      .where({ hashed_team_id: teamHash, status: 'active' }).forShare();
    if (!members.some((row) => row.hashed_user_id === actorHash && TEAM_ROTATION_ROLES.has(row.role))) {
      reject(403, 'team_permission_denied');
    }
    if (!team.rotation_pending || epoch !== (team.team_key_epoch ?? 1) + 1) {
      reject(409, 'team_key_epoch_conflict');
    }
    // A concurrent profile edit must survive; the admin retries with its current ciphertext.
    const profile = rotatedProfile(team, body.profile);
    requireCoverage(memberWrappers, members.map((row) => row.hashed_user_id), 'team_key_member_set_changed');
    const projects = await trx('project_key_wrappers').where({ hashed_team_id: teamHash, key_type: 'team' }).forUpdate();
    requireCoverage(projectWrappers, projects.map((row) => row.hashed_project_id), 'team_key_project_set_changed');

    const now = Math.floor(Date.now() / 1000);
    for (const project of projects) {
      await trx('project_key_wrappers').where({ id: project.id }).update({
        encrypted_project_key: projectWrappers.get(project.hashed_project_id),
        team_key_epoch: epoch,
      });
    }
    await trx('team_key_wrappers').where({ hashed_team_id: teamHash }).del();
    const wrappers = [...memberWrappers].map(([userHash, cipher]) => ({
      id: randomUUID(), hashed_team_id: teamHash, hashed_user_id: userHash, team_key_epoch: epoch,
      encrypted_team_key: cipher, status: 'active', created_at: now, revoked_at: null,
    }));
    await trx('team_key_wrappers').insert(wrappers);
    await trx('teams').where({ id: team.id }).update({
      ...profile,
      team_key_epoch: epoch, rotation_pending: false, encrypted_previous_team_keys: previous, updated_at: now,
    });
    return { team_key_epoch: epoch };
  });
}
