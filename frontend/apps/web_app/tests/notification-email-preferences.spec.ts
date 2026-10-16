/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { allowConsoleErrorPatterns } = require('./console-monitor');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const credentials = getTestAccount();

type SettingsSnapshot = {
    enabled: boolean;
    preferences: Record<string, boolean>;
    choices?: Record<string, { source: string; value: boolean }>;
};

type TrackedSettings = {
    latest?: SettingsSnapshot;
    reads: Set<string>;
    writes: Set<string>;
    frames: Array<{
        direction: 'sent' | 'received';
        type: string;
        request_id?: string;
        preferences?: Record<string, boolean>;
        choices?: Record<string, { source?: string; value?: boolean }>;
    }>;
    matchedSnapshots: number;
    matchedAcks: number;
    matchedErrors: number;
    correlationErrors: string[];
};

const settingsByPage = new WeakMap<any, TrackedSettings>();
const trackedPages: any[] = [];
const SETTING_KEYS = ['enabled', 'aiResponses', 'workflowRuns', 'includeContent', 'backupReminder', 'webhookChats'];

function recordSettingsFrame(state: TrackedSettings, direction: 'sent' | 'received', message: any): void {
    if (!['email_notification_settings_get', 'email_notification_settings', 'email_notification_settings_snapshot',
        'email_notification_settings_ack', 'email_notification_settings_updated', 'error'].includes(message.type)) return;
    const payload = message.payload;
    const preferences = Object.fromEntries(
        SETTING_KEYS.filter((key) => key !== 'enabled' && typeof payload?.preferences?.[key] === 'boolean')
            .map((key) => [key, payload.preferences[key]])
    );
    const choices = Object.fromEntries(
        SETTING_KEYS.filter((key) => payload?.choices?.[key] && typeof payload.choices[key] === 'object')
            .map((key) => [key, {
                ...(typeof payload.choices[key].source === 'string'
                    ? { source: payload.choices[key].source === 'user' ? 'user' : 'other' } : {}),
                ...(typeof payload.choices[key].value === 'boolean' ? { value: payload.choices[key].value } : {})
            }])
    );
    state.frames.push({
        direction,
        type: message.type,
        ...(typeof payload?.request_id === 'string' ? { request_id: payload.request_id } : {}),
        ...(Object.keys(preferences).length ? { preferences } : {}),
        ...(Object.keys(choices).length ? { choices } : {})
    });
    if (state.frames.length > 120) state.frames.shift();
}

test.beforeEach(() => { trackedPages.length = 0; });
// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
    if (testInfo.status === testInfo.expectedStatus) return;
    const frames = trackedPages.map((page, index) => ({
        page: index + 1,
        frames: settingsByPage.get(page)?.frames ?? []
    }));
    await testInfo.attach('notification-settings-frames', {
        body: Buffer.from(JSON.stringify(frames)),
        contentType: 'application/json'
    });
});

function trackSettings(page: any): void {
    const state: TrackedSettings = {
        reads: new Set(), writes: new Set(), frames: [],
        matchedSnapshots: 0, matchedAcks: 0, matchedErrors: 0, correlationErrors: []
    };
    settingsByPage.set(page, state);
    trackedPages.push(page);
    page.on('websocket', (socket: any) => {
        socket.on('framesent', (frame: { payload: string }) => {
            try {
                const message = JSON.parse(String(frame.payload));
                if (message.type !== 'email_notification_settings_get' && message.type !== 'email_notification_settings') return;
                recordSettingsFrame(state, 'sent', message);
                const requestId = message.payload?.request_id;
                if (typeof requestId !== 'string' || !requestId) {
                    state.correlationErrors.push(`${message.type} omitted request_id`);
                    return;
                }
                (message.type === 'email_notification_settings_get' ? state.reads : state.writes).add(requestId);
            } catch { /* Other WebSocket frames need no inspection here. */ }
        });
        socket.on('framereceived', (frame: { payload: string }) => {
            try {
                const message = JSON.parse(String(frame.payload));
                recordSettingsFrame(state, 'received', message);
                let appliesToThisPage = false;
                if (message.type === 'email_notification_settings_snapshot' || message.type === 'email_notification_settings_ack') {
                    const pending = message.type === 'email_notification_settings_snapshot' ? state.reads : state.writes;
                    const requestId = message.payload?.request_id;
                    if (typeof requestId !== 'string') {
                        state.correlationErrors.push(`${message.type} omitted request_id`);
                    } else if (pending.delete(requestId)) {
                        if (message.type === 'email_notification_settings_snapshot') state.matchedSnapshots += 1;
                        else state.matchedAcks += 1;
                        appliesToThisPage = true;
                    }
                }
                if (message.type === 'email_notification_settings_updated' && message.payload?.request_id !== undefined) {
                    state.correlationErrors.push('cross-device broadcast exposed request_id');
                }
                if (message.type === 'email_notification_settings_updated') appliesToThisPage = true;
                if (message.type === 'error' && typeof message.payload?.request_id === 'string' && state.writes.delete(message.payload.request_id)) {
                    state.matchedErrors += 1;
                }
                if (appliesToThisPage) {
                    state.latest = message.payload;
                }
            } catch { /* Other WebSocket frames need no inspection here. */ }
        });
    });
}

function expectSettingsCorrelated(page: any, kind: 'snapshot' | 'ack'): void {
    const state = settingsByPage.get(page);
    expect(state?.correlationErrors).toEqual([]);
    expect(kind === 'snapshot' ? state?.matchedSnapshots : state?.matchedAcks).toBeGreaterThan(0);
}

async function persistedPreferences(page: any): Promise<Record<string, boolean>> {
    const preferences = settingsByPage.get(page)?.latest?.preferences;
    if (!preferences) throw new Error('No durable notification settings response received');
    return preferences;
}

async function openEmailSettings(page: any): Promise<any> {
    const menu = page.locator('[data-testid="settings-menu"].visible');
    if (!await menu.isVisible()) await page.getByTestId('profile-container').click();
    await menu.getByRole('menuitem', { name: /^notifications$/i }).first().click();
    const snapshot = page.waitForEvent('console', {
        predicate: (message: any) => message.text().includes('email_notification_settings_snapshot received'),
        timeout: 30_000
    });
    await menu.getByRole('menuitem', { name: /chat/i }).first().click();
    const section = page.getByTestId('email-section');
    await expect(section).toBeVisible();
    await snapshot;
    expectSettingsCorrelated(page, 'snapshot');
    return section;
}

async function openBackupSettings(page: any): Promise<any> {
    const menu = page.locator('[data-testid="settings-menu"].visible');
    if (!await menu.isVisible()) await page.getByTestId('profile-container').click();
    await menu.getByRole('menuitem', { name: /^notifications$/i }).first().click();
    const snapshot = page.waitForEvent('console', {
        predicate: (message: any) => message.text().includes('email_notification_settings_snapshot received'),
        timeout: 30_000
    });
    await menu.getByRole('menuitem', { name: /backup/i }).first().click();
    const toggle = page.getByTestId('email-backup-reminder');
    await expect(toggle).toBeVisible();
    const checkbox = toggle.locator('input[type="checkbox"]');
    await snapshot;
    expectSettingsCorrelated(page, 'snapshot');
    return checkbox;
}

function preference(section: any, key: string): any {
    return section.getByTestId(`email-notifications-${key}`).locator('input[type="checkbox"]');
}

async function toggleAndWaitForAck(page: any, checkbox: any): Promise<void> {
    const ack = page.waitForEvent('console', {
        predicate: (message: any) => message.text().includes('email_notification_settings_ack received'),
        timeout: 30_000
    });
    await checkbox.locator('..').click();
    await ack;
    expectSettingsCorrelated(page, 'ack');
}

// contract-test: direct surface=gui.web assertions=notifications.settings.ack-persisted
test('email categories and preview consent persist independently across reload and clients', async ({ page, browser }: { page: any; browser: any }) => {
    skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
    test.setTimeout(240_000);
    trackSettings(page);
    await loginToTestAccount(page, undefined, undefined, { waitForEditor: false, credentials });
    let section = await openEmailSettings(page);

    const master = preference(section, 'master');
    const originallyEnabled = await master.isChecked();
    const initialSnapshot = settingsByPage.get(page)?.latest;
    expect(initialSnapshot?.enabled).toBe(originallyEnabled);

    // Change one outbound write into an invalid request while retaining its ID.
    // The server rejects it, and the optimistic toggle must return to durable state.
    const errorsBefore = settingsByPage.get(page)?.matchedErrors ?? 0;
    allowConsoleErrorPatterns([
        /^\[WebSocketService\] Received error message from server:.*\bInvalid notification setting\.(?:["',}\s]|$)/
    ]);
    await page.evaluate(() => {
        const send = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data: string | ArrayBufferLike | Blob | ArrayBufferView) {
            if (typeof data === 'string') {
                try {
                    const message = JSON.parse(data);
                    if (message.type === 'email_notification_settings') {
                        WebSocket.prototype.send = send;
                        message.payload.enabled = 'invalid';
                        return send.call(this, JSON.stringify(message));
                    }
                } catch { /* Pass through other frames. */ }
            }
            return send.call(this, data);
        };
    });
    await master.locator('..').click();
    await expect.poll(() => settingsByPage.get(page)?.matchedErrors).toBe(errorsBefore + 1);
    await expect(
        page.locator('[data-testid="notification"].notification-error .notification-message-primary')
            .filter({ hasText: 'Server error: Invalid notification setting.' })
    ).toBeVisible();
    await expect(master).toHaveJSProperty('checked', originallyEnabled);
    expectSettingsCorrelated(page, 'snapshot');
    expect(settingsByPage.get(page)?.latest?.enabled).toBe(originallyEnabled);

    for (const [key, testId] of [['aiResponses', 'ai-responses'], ['workflowRuns', 'workflow-runs'], ['includeContent', 'include-content']]) {
        if (initialSnapshot?.choices?.[key]?.source === 'user' && initialSnapshot.choices[key].value === false) {
            expect(initialSnapshot.preferences[key]).toBe(false);
        }
        if (originallyEnabled) expect(await preference(section, testId).isChecked()).toBe(initialSnapshot?.preferences[key]);
    }
    if (!originallyEnabled) await toggleAndWaitForAck(page, master);

    const original: Record<string, boolean> = {};
    const originalPersisted = await persistedPreferences(page);
    for (const key of ['ai-responses', 'workflow-runs', 'include-content', 'webhook-chats']) {
        original[key] = await preference(section, key).isChecked();
    }
    await expect(section).toContainText('Allow chat and workflow titles and previews in email.');
    await expect(section).toContainText('Your email provider can read this content.');

    // Keep a second client open on its initial backup settings snapshot while the first
    // changes chat categories. Its later save must not replay that snapshot over them.
    const secondContext = await browser.newContext();
    const secondPage = await secondContext.newPage();
    trackSettings(secondPage);
    await loginToTestAccount(secondPage, undefined, undefined, { waitForEditor: false, credentials });
    const backupCheckbox = await openBackupSettings(secondPage);
    const originalBackup = await backupCheckbox.isChecked();
    let backupChanged = false;

    try {
        await toggleAndWaitForAck(page, preference(section, 'ai-responses'));
        await expect(preference(section, 'ai-responses')).toHaveJSProperty('checked', !original['ai-responses']);
        await expect(preference(section, 'workflow-runs')).toHaveJSProperty('checked', original['workflow-runs']);
        await expect(preference(section, 'webhook-chats')).toHaveJSProperty('checked', original['webhook-chats']);
        const saved = await persistedPreferences(page);
        expect(saved.backupReminder).toBe(originalPersisted.backupReminder);
        expect(saved.webhookChats).toBe(originalPersisted.webhookChats);

        await toggleAndWaitForAck(page, preference(section, 'workflow-runs'));
        await toggleAndWaitForAck(page, preference(section, 'include-content'));
        const snapshotsBeforeReload = settingsByPage.get(page)?.matchedSnapshots ?? 0;
        await page.reload();
        // Reload restores the open Chat Notifications panel. Wait for its fresh
        // server snapshot instead of racing the settings-menu transition.
        section = page.getByTestId('email-section');
        await expect(section).toBeVisible();
        await expect.poll(() => settingsByPage.get(page)?.matchedSnapshots ?? 0)
            .toBeGreaterThan(snapshotsBeforeReload);
        expectSettingsCorrelated(page, 'snapshot');

        await expect(preference(section, 'ai-responses')).toHaveJSProperty('checked', !original['ai-responses']);
        await expect(preference(section, 'workflow-runs')).toHaveJSProperty('checked', !original['workflow-runs']);
        await expect(preference(section, 'include-content')).toHaveJSProperty('checked', !original['include-content']);
        await expect(preference(section, 'webhook-chats')).toHaveJSProperty('checked', original['webhook-chats']);
        const persistedAfterReload = await persistedPreferences(page);
        expect(persistedAfterReload.backupReminder).toBe(originalPersisted.backupReminder);
        expect(persistedAfterReload.webhookChats).toBe(originalPersisted.webhookChats);

        await backupCheckbox.locator('..').click();
        backupChanged = true;
        await expect.poll(() => settingsByPage.get(secondPage)?.writes.size).toBe(0);
        await expect.poll(async () => (await persistedPreferences(page)).backupReminder).toBe(!originalBackup);
        const afterOtherClientSave = await persistedPreferences(page);
        expect(afterOtherClientSave.aiResponses).toBe(!original['ai-responses']);
        expect(afterOtherClientSave.workflowRuns).toBe(!original['workflow-runs']);
        expect(afterOtherClientSave.includeContent).toBe(!original['include-content']);
        expect(afterOtherClientSave.webhookChats).toBe(originalPersisted.webhookChats);
    } finally {
        if (backupChanged && await backupCheckbox.locator('..').isVisible().catch(() => false)) {
            await backupCheckbox.locator('..').click();
            await expect.poll(() => settingsByPage.get(secondPage)?.writes.size).toBe(0);
            await expect.poll(async () => (await persistedPreferences(page)).backupReminder).toBe(originalBackup);
        }
        await secondContext.close();
        for (const key of ['ai-responses', 'workflow-runs', 'include-content']) {
            const checkbox = preference(section, key);
            if (await checkbox.locator('..').isVisible().catch(() => false) && await checkbox.isChecked() !== original[key]) {
                await toggleAndWaitForAck(page, checkbox);
            }
        }
        if (!originallyEnabled && await master.locator('..').isVisible().catch(() => false)) {
            await toggleAndWaitForAck(page, preference(section, 'master'));
        }
    }

    for (const trackedPage of [page, secondPage]) {
        const state = settingsByPage.get(trackedPage);
        expect(state?.reads.size).toBe(0);
        expect(state?.writes.size).toBe(0);
        expect(state?.correlationErrors).toEqual([]);
    }
});
