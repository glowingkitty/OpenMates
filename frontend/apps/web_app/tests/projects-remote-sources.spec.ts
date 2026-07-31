/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

function projectHashUrlPattern(projectId: string): RegExp {
  return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  test('renders attached remote source status in Projects', async ({ page }) => {
    test.setTimeout(120000);

    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

    const projectName = `E2E Remote Source ${Date.now().toString(36)}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await page.getByTestId('project-input-submit').click();
    const createdProjectId = (await (await created).json()).project.project_id;
    await expect(page).toHaveURL(projectHashUrlPattern(createdProjectId));
    await expect(page.getByTestId('workspace-detail-title')).toHaveText(projectName, { timeout: 30000 });

    const sourceId = `source-${Date.now()}`;
    const sourcePayload = await page.evaluate(async ({ name, apiBaseUrl, sourceId, projectId }) => {
      const bytesFromBase64 = (base64) => {
        let standard = base64.replace(/-/g, '+').replace(/_/g, '/');
        const missingPadding = standard.length % 4;
        if (missingPadding) standard += '='.repeat(4 - missingPadding);
        const binary = window.atob(standard);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        return bytes;
      };
      const base64FromBytes = (bytes) => {
        let binary = '';
        for (const byte of bytes) binary += String.fromCharCode(byte);
        return window.btoa(binary);
      };
      const readMasterKey = async () => new Promise((resolve, reject) => {
        const request = indexedDB.open('openmates_crypto', 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const db = request.result;
          const transaction = db.transaction(['keys'], 'readonly');
          const store = transaction.objectStore('keys');
          const keyRequest = store.get('master_key');
          keyRequest.onerror = () => reject(keyRequest.error);
          keyRequest.onsuccess = () => resolve(keyRequest.result || null);
          transaction.oncomplete = () => db.close();
        };
      });
      const decryptProjectKey = async (encryptedProjectKey, masterKey) => {
        const combined = bytesFromBase64(encryptedProjectKey);
        const iv = combined.slice(0, 12);
        const ciphertext = combined.slice(12);
        const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, masterKey, ciphertext);
        return new Uint8Array(decrypted);
      };
      const encryptWithProjectKey = async (text, projectKey) => {
        const cryptoKey = await crypto.subtle.importKey('raw', new Uint8Array(projectKey), { name: 'AES-GCM' }, false, ['encrypt']);
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const plaintext = new TextEncoder().encode(text);
        const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, plaintext);
        const combined = new Uint8Array(iv.length + encrypted.byteLength);
        combined.set(iv);
        combined.set(new Uint8Array(encrypted), iv.length);
        return base64FromBytes(combined);
      };

      const response = await fetch(`${apiBaseUrl}/v1/projects`, { credentials: 'include' });
      if (!response.ok) throw new Error(`Project list failed: ${response.status}`);
      const data = await response.json();
      const projects = Array.isArray(data.projects) ? data.projects : [];
      const latest = projects.find((project) => project.project_id === projectId);
      if (!latest?.project_id) throw new Error(`Could not resolve project id for ${name}`);
      if (!latest.encrypted_project_key) throw new Error(`Could not resolve encrypted project key for ${name}`);
      const masterKey = await readMasterKey();
      if (!masterKey) throw new Error('Master key unavailable for encrypted Project source fixture');
      const projectKey = await decryptProjectKey(latest.encrypted_project_key, masterKey);
      const remoteFileContent = 'export const remoteDemo = "OpenMates remote preview";\nexport const imported = true;\n';
      const metadata = {
        root: '/workspace/openmates',
        preview_files: [{
          path: 'src/remote-demo.ts',
          display_name: 'remote-demo.ts',
          language: 'typescript',
          snippet: remoteFileContent,
          full_content: remoteFileContent,
          size_bytes: remoteFileContent.length,
          line_count: 2,
          content_hash: 'e2e-remote-demo-hash',
          git_status: 'modified',
          safety_flags: [],
        }],
      };
      return {
        projectId: latest.project_id,
        encryptedDisplayName: await encryptWithProjectKey(sourceId, projectKey),
        encryptedMetadata: await encryptWithProjectKey(JSON.stringify(metadata), projectKey),
      };
    }, { name: projectName, apiBaseUrl: API_BASE_URL, sourceId, projectId: createdProjectId });

    await page.evaluate(async ({ apiBaseUrl, projectId, sourceId, encryptedDisplayName, encryptedMetadata }) => {
      const timestamp = Math.floor(Date.now() / 1000);
      const response = await fetch(`${apiBaseUrl}/v1/projects/${encodeURIComponent(projectId)}/sources`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_id: sourceId,
          source_type: 'remote_git_repository',
          encrypted_display_name: encryptedDisplayName,
          encrypted_metadata: encryptedMetadata,
          capabilities: ['read', 'search', 'import'],
          status: 'connected',
          created_at: timestamp,
          updated_at: timestamp,
        }),
      });
      if (!response.ok) throw new Error(`Project source create failed: ${response.status} ${await response.text()}`);
    }, { apiBaseUrl: API_BASE_URL, projectId: sourcePayload.projectId, sourceId, encryptedDisplayName: sourcePayload.encryptedDisplayName, encryptedMetadata: sourcePayload.encryptedMetadata });

    await page.reload();
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveURL(projectHashUrlPattern(sourcePayload.projectId));
    await expect(page.getByTestId('workspace-detail-title')).toHaveText(projectName, { timeout: 30000 });
    await expect(page.getByTestId('project-remote-sources-section')).toBeVisible();
    await expect(page.getByTestId('project-remote-source-card').filter({ hasText: sourceId })).toBeVisible();
    await expect(page.getByTestId('project-remote-source-card').filter({ hasText: 'connected' })).toBeVisible();
    const remotePreview = page.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).first();
    await expect(remotePreview).toBeVisible();
    await expect(remotePreview).toContainText('remoteDemo');
    await remotePreview.getByTestId('project-remote-preview-open').click();
    const fullscreenOverlay = page.getByTestId('project-remote-fullscreen-overlay');
    await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
    await expect(fullscreenOverlay).toContainText('remote-demo.ts');
    await closeFullscreen(page, fullscreenOverlay);
    await remotePreview.getByTestId('project-remote-preview-upload').click();
    await expect(page.getByTestId('project-item-card').filter({ hasText: 'remote-demo.ts' }).first()).toBeVisible({ timeout: 30000 });

    await page.getByTestId('project-settings-button').click();
    const projectSettings = page.locator(`[data-testid="settings-menu"][data-active-view="projects/${sourcePayload.projectId}"]`);
    await expect(projectSettings).toBeVisible({ timeout: 10000 });
    await expect(projectSettings.getByTestId('project-settings-page')).toBeVisible();
    await expect(projectSettings.getByTestId('project-settings-title')).toContainText(projectName, { timeout: 30000 });
    await expect(projectSettings.getByTestId('project-settings-source-card').filter({ hasText: sourceId })).toBeVisible();
    await projectSettings.getByTestId('project-settings-write-mode-safe-writes').click();
    await expect(projectSettings).toContainText('Project write policy saved.');
    await expect(projectSettings).toContainText('Auto approve safe writes');

    await page.getByTestId('icon-button-close').click();

    await expect(page.getByTestId('chats-nav-link')).toBeVisible({ timeout: 30000 });
    await page.getByTestId('chats-nav-link').click();
    await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 30000 });
    if (await page.getByTestId('login-wrapper').isVisible({ timeout: 15000 }).catch(() => false)) {
      const loginTab = page.getByTestId('tab-login');
      if (await loginTab.isVisible({ timeout: 3000 }).catch(() => false)) await loginTab.click();
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('closeLoginInterface')));
    }
    await expect(page.getByTestId('login-wrapper')).toHaveCount(0, { timeout: 30000 });
    await startNewChat(page);
    const messageField = page.getByTestId('message-field').last();
    await expect(messageField).toBeVisible({ timeout: 30000 });
    const messageEditor = messageField.getByTestId('message-editor');
    const editableMessage = messageEditor.locator('[contenteditable="true"]');
    await expect(editableMessage).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('login-wrapper')).toHaveCount(0);
    await editableMessage.click();
    const mentionQuery = `@${projectName.slice(projectName.lastIndexOf(' ') + 1)}`;
    await page.keyboard.insertText(mentionQuery);
    await expect
      .poll(async () => ((await messageEditor.textContent()) || '').replace(/\s+/g, ' ').trim(), { timeout: 10000 })
      .toContain(mentionQuery);
    const mentionDropdown = page.getByTestId('mention-dropdown');
    await expect(mentionDropdown).toBeVisible({ timeout: 30000 });
    const projectMention = mentionDropdown.getByTestId('mention-result').filter({ hasText: projectName }).first();
    await expect(projectMention).toBeVisible({ timeout: 30000 });
    await projectMention.click();

    const editor = page.getByTestId('message-editor');
    await expect(editor.getByTestId('project-access-chip')).toBeVisible({ timeout: 30000 });
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read & Write');
    await editor.getByTestId('project-access-chip').press('Enter');
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read');

    await page.goto('/projects');
    const projectCard = page.getByTestId('project-landing-card').filter({ hasText: projectName }).first();
    await expect(projectCard).toBeVisible({ timeout: 30000 });
    await projectCard.click();
    await expect(page).toHaveURL(projectHashUrlPattern(sourcePayload.projectId));
    const deleted = page.waitForResponse(
      (response) => response.request().method() === 'DELETE' && response.url().endsWith(`/v1/projects/${sourcePayload.projectId}`) && response.ok()
    );
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await deleted;
    await expect(page.getByTestId('projects-start-screen')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('project-landing-card').filter({ hasText: projectName })).toHaveCount(0);
  });
});
