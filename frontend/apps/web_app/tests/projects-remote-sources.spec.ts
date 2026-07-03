/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await loginToTestAccount(page);
  });

  test('renders attached remote source status in Projects', async ({ page }) => {
    test.setTimeout(120000);

    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

    const projectName = `E2E Remote Source ${Date.now()}`;
    await page.getByTestId('project-create-main-button').click();
    await expect(page.getByTestId('projects-sidebar')).toBeVisible();
    await page.getByTestId('project-name-input').fill(projectName);
    await page.getByTestId('project-create-button').click();
    await expect(page.getByTestId('project-card').filter({ hasText: projectName }).first()).toBeVisible();

    const sourceId = `source-${Date.now()}`;
    const sourcePayload = await page.evaluate(async ({ name, apiBaseUrl, sourceId }) => {
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
      const latest = projects.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
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
    }, { name: projectName, apiBaseUrl: API_BASE_URL, sourceId });

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
    await expect(page.getByTestId('project-card').filter({ hasText: projectName }).first()).toBeVisible();
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
    await expect(projectSettings.getByTestId('project-settings-title')).toContainText(projectName);
    await expect(projectSettings.getByTestId('project-settings-source-card').filter({ hasText: sourceId })).toBeVisible();
    await projectSettings.getByTestId('project-settings-write-mode-safe-writes').click();
    await expect(projectSettings).toContainText('Project write policy saved.');
    await expect(projectSettings).toContainText('Auto approve safe writes');

    await page.getByTestId('icon-button-close').click();

    await page.goto('/');
    const newChatButton = page.getByTestId('new-chat-button');
    if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatButton.click();
    }
    await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
    const messageEditor = page.getByTestId('message-editor');
    const editableMessage = messageEditor.locator('[contenteditable="true"]');
    await editableMessage.click();
    await editableMessage.pressSequentially('@', { delay: 50 });
    await expect(editableMessage).toContainText('@');
    await expect(page.getByTestId('mention-dropdown')).toBeVisible();
    await page.getByTestId('mention-result').filter({ hasText: projectName }).first().click();

    const editor = page.getByTestId('message-editor');
    await expect(editor.locator('[data-mention-type="project"], [data-mention-type="project_folder"], [data-mention-type="project_file"]')).toBeVisible();
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read & Write');
    await editor.getByTestId('project-access-chip').press('Enter');
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read');

    await page.goto('/projects');
    const projectCard = page.getByTestId('project-card').filter({ hasText: projectName }).first();
    await expect(projectCard).toBeVisible({ timeout: 30000 });
    await projectCard.click();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await expect(page.getByTestId('project-card').filter({ hasText: projectName })).toHaveCount(0);
  });
});
