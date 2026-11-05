/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCliJson, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { randomUUID, randomBytes, createHash, createCipheriv, createDecipheriv } = require('node:crypto');

function encrypt(key: Buffer, text: string): string {
  const iv = randomBytes(12), cipher = createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]);
  return Buffer.concat([iv, ciphertext, cipher.getAuthTag()]).toString('base64');
}
function decrypt(key: Buffer, encoded: string): string {
  const bytes = Buffer.from(encoded, 'base64');
  const cipher = createDecipheriv('aes-256-gcm', key, bytes.subarray(0, 12));
  cipher.setAuthTag(bytes.subarray(-16));
  return Buffer.concat([cipher.update(bytes.subarray(12, -16)), cipher.final()]).toString('utf8');
}

test.describe('Project Specification ciphertext lifecycle', () => {
  test.setTimeout(240_000);
  // contract-test: direct surface=rest_api assertions=contracts.authoring.shared-direct-and-chat,contracts.revision.optimistic-conflict,contracts.revision.exact-approval,contracts.project.encrypted-embed,contracts.links.revision-traceable
  test('saved revisions survive reload, conflicting edits preserve approved content, and Project access is scoped', async ({ page, playwright }) => {
    const { email, password, otpKey } = getTestAccount();
    skipWithoutCredentials(test, email, password, otpKey);
    const base = workflowApiUrl(), cliHome = createWorkflowCliHome('specification-lifecycle');
    const projects: string[] = [];
    let movedTeamId = '';
    const key = randomBytes(32), specificationId = randomUUID(), firstRevision = randomUUID();
    const hash = (value: string) => createHash('sha256').update(value).digest('hex');
    const document = (revision: string, text: string) => ({
      revision_id: revision, content_hash: hash(text), project_surface_catalog_revision_id: 'catalog-1',
      encrypted_title: encrypt(key, 'Recipe planning'), encrypted_summary: encrypt(key, 'Save recipes and plan meals'),
      encrypted_specification_document: encrypt(key, text),
    });
    try {
      await loginWorkflowCliViaPair(page, base, cliHome, 'SPECIFICATION_LIFECYCLE');
      for (const label of ['home', 'unrelated']) {
        const result = await runWorkflowCliJson(base, cliHome, ['projects', 'create', `Spec lifecycle ${label} ${Date.now()}`, '--write-policy', 'always_ask', '--personal'], 'create disposable Specification Project');
        projects.push(result.project.project_id);
      }
      const prefix = `${base}/v1/projects/${projects[0]}/specifications`;
      const initial = { ...document(firstRevision, 'A user can save a recipe.'), specification_id: specificationId,
        key_wrappers: [
          { key_type: 'project', hashed_project_id: hash(projects[0]), encrypted_specification_key: encrypt(randomBytes(32), key.toString('base64')) },
          { key_type: 'master', encrypted_specification_key: encrypt(randomBytes(32), key.toString('base64')) },
        ] };
      const create = await page.request.post(prefix, { data: initial });
      expect(create.status(), await create.text()).toBe(201);
      expect((await create.json()).specification.current_revision_number).toBe(1);
      const retry = await page.request.post(prefix, { data: initial });
      expect(retry.status()).toBe(201);
      expect((await retry.json()).replayed).toBe(true);

      const approve = await page.request.post(`${prefix}/${specificationId}/approve`, { data: { revision_id: firstRevision, content_hash: initial.content_hash } });
      expect(approve.status(), await approve.text()).toBe(200);
      expect((await approve.json()).revision.approval_state).toBe('approved');

      const edits = [document(randomUUID(), 'A user can save and export recipes.'), document(randomUUID(), 'A user can assign recipes to a week.')];
      const responses = await Promise.all(edits.map((edit) => page.request.post(`${prefix}/${specificationId}/revisions`, { data: { ...edit, base_revision_id: firstRevision } })));
      expect(responses.map((response) => response.status()).sort()).toEqual([200, 409]);
      const winner = await responses.find((response) => response.status() === 200)!.json();
      const winnerIndex = responses.findIndex((response) => response.status() === 200);
      expect(winner.revision.approval_state).toBe('draft');
      expect(winner.specification.current_revision_number).toBe(2);
      await page.reload();
      const loaded = await page.request.get(`${prefix}/${specificationId}`);
      expect(loaded.status()).toBe(200);
      const stored = await loaded.json();
      expect(stored.revision.revision_id).toBe(edits[winnerIndex].revision_id);
      expect(decrypt(key, stored.revision.encrypted_specification_document)).toBe(winnerIndex === 0 ? 'A user can save and export recipes.' : 'A user can assign recipes to a week.');

      const old = await page.request.get(`${prefix}/${specificationId}?revision_id=${firstRevision}`);
      expect(old.status()).toBe(200);
      const oldRevision = (await old.json()).revision;
      expect(oldRevision.approval_state).toBe('approved');
      expect(decrypt(key, oldRevision.encrypted_specification_document)).toBe('A user can save a recipe.');
      const staleApproval = await page.request.post(`${prefix}/${specificationId}/approve`, { data: { revision_id: firstRevision, content_hash: initial.content_hash } });
      expect(staleApproval.status()).toBe(409);
      const history = await page.request.get(`${prefix}/${specificationId}/revisions?limit=1`);
      expect(history.status()).toBe(200);
      expect((await history.json()).next_cursor).toBe(2);
      const earlier = await page.request.get(`${prefix}/${specificationId}/revisions?before=2`);
      expect((await earlier.json()).revisions.map((revision) => revision.revision_id)).toEqual([firstRevision]);
      const crossProject = await page.request.get(`${base}/v1/projects/${projects[1]}/specifications/${specificationId}`);
      expect(crossProject.status()).toBe(404);
      const unauthenticated = await playwright.request.newContext();
      try {
        expect([401, 403]).toContain((await unauthenticated.get(`${prefix}/${specificationId}`)).status());
      } finally { await unauthenticated.dispose(); }
      const invalid = await page.request.post(prefix, { data: { ...initial, specification_id: randomUUID(), plaintext: 'This must never be persisted.' } });
      expect(invalid.status()).toBe(422);

      const createdTeam = await runWorkflowCliJson(base, cliHome, ['teams', 'create', '--name', `Spec move ${Date.now()}`], 'create disposable move Team');
      const teamId = createdTeam.team.team_id;
      // The backend receives opaque wrapped-key fixtures here; this API test
      // proves scope and ciphertext preservation, not SDK key restoration.
      const moved = await page.request.post(`${base}/v1/projects/${projects[0]}/move`, { data: {
        team_id: teamId, confirmed: true, encrypted_slug: encrypt(key, 'recipe-planning'),
        slug_lookup_hash: hash(`${teamId}:${projects[0]}`),
        team_project_key_wrapper: { key_type: 'team', hashed_team_id: hash(teamId), team_key_epoch: 1,
          encrypted_project_key: encrypt(randomBytes(32), randomBytes(32).toString('base64')), created_at: Math.floor(Date.now() / 1000) },
      } });
      expect(moved.status(), await moved.text()).toBe(200);
      movedTeamId = teamId;
      expect((await page.request.get(`${prefix}/${specificationId}`)).status()).toBe(404);
      const teamRead = await page.request.get(`${prefix}/${specificationId}?team_id=${teamId}`);
      expect(teamRead.status(), await teamRead.text()).toBe(200);
      const teamRecord = await teamRead.json();
      expect(teamRecord.specification.hashed_user_id).toBeNull();
      expect(teamRecord.specification.hashed_team_id).toBe(hash(teamId));
      expect(teamRecord.specification.key_wrappers.map((wrapper) => wrapper.key_type)).toEqual(['project']);
      expect(teamRecord.revision.encrypted_specification_document).toBe(stored.revision.encrypted_specification_document);
      const teamChange = document(randomUUID(), 'A household can plan its week.');
      const teamSaved = await page.request.post(`${prefix}/${specificationId}/revisions?team_id=${teamId}`, {
        data: { ...teamChange, base_revision_id: stored.revision.revision_id },
      });
      expect(teamSaved.status(), await teamSaved.text()).toBe(200);
      const teamApproved = await page.request.post(`${prefix}/${specificationId}/approve?team_id=${teamId}`, {
        data: { revision_id: teamChange.revision_id, content_hash: teamChange.content_hash },
      });
      expect(teamApproved.status(), await teamApproved.text()).toBe(200);
      const movedHistory = await page.request.get(`${prefix}/${specificationId}/revisions?team_id=${teamId}`);
      expect((await movedHistory.json()).revisions).toHaveLength(3);
    } finally {
      // All persisted state is confined to disposable CI Projects/accounts.
      for (const projectId of projects) {
        const params = new URLSearchParams({ confirmation_project_id: projectId });
        if (projectId === projects[0] && movedTeamId) params.set('team_id', movedTeamId);
        const removed = await page.request.delete(`${base}/v1/projects/${projectId}?${params}`);
        // Keep a preceding assertion visible if cleanup also fails.
        expect.soft(removed.ok(), `delete disposable Specification Project: ${removed.status()} ${await removed.text()}`).toBe(true);
      }
      removeWorkflowCliHome(cliHome);
    }
  });
});
