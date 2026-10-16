/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, waitForChatReady, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { waitForEmbedFinished, openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { runCli, deriveApiUrl } = require('./helpers/cli-test-helpers');
const { execFileSync } = require('node:child_process');
const { existsSync } = require('node:fs');
const path = require('node:path');

test.setTimeout(300_000);

// Retain dispatch diagnostics before the isolated stack's final log tail rolls
// past the send. Only event types, booleans, counts and fixed stage labels leave
// the runner; message bodies, ciphertext, identifiers and credentials do not.
function captureDispatch(page: any) {
  const events: Record<string, unknown>[] = [];
  const startedAt = new Date().toISOString();
  const types = new Set(['chat_turn_preflight', 'chat_turn_preflight_ack',
    'chat_message_added', 'chat_message_confirmed', 'request_chat_history',
    'message_queued', 'queued_handoff_paused', 'ai_task_initiated', 'error']);
  page.on('websocket', (socket: any) => {
    const capture = (direction: string) => (frame: any) => {
      try {
        const message = JSON.parse(String(frame.payload));
        const type = message.type || message.event;
        if (!types.has(type) || events.length >= 100) return;
        const payload = message.payload || {};
        const request = payload.inference_request || payload;
        const body = request.message || request;
        const label = (value: unknown) => typeof value === 'string'
          && /^[a-zA-Z0-9_]{1,80}$/.test(value) ? value : undefined;
        events.push({ direction, type,
          protocolVersionPresent: payload.protocol_version !== undefined,
          preflightPresent: Boolean(payload.preflight_id),
          teamPresent: Boolean(payload.team_id),
          historyCount: Array.isArray(request.message_history) ? request.message_history.length : undefined,
          testMockMarkerPresent: Boolean(request.test_mock_marker)
            || (typeof body.content === 'string' && body.content.includes('TEST_MOCK')),
          reason: label(payload.reason), code: label(payload.code), status: label(payload.status), state: label(payload.state),
        });
      } catch { /* Ignore binary/non-JSON frames. */ }
    };
    socket.on('framesent', capture('sent'));
    socket.on('framereceived', capture('received'));
  });
  return () => {
    const stages: string[] = [];
    const composeFile = path.resolve(__dirname, '../../../../test-results/ci-private/compose.json');
    if (existsSync(composeFile)) {
      try {
        const output = execFileSync('docker', ['compose', '-f', composeFile,
          'logs', '--no-color', '--since', startedAt, '--tail', '3000', 'api', 'ai-worker'],
        { encoding: 'utf8', timeout: 15_000, maxBuffer: 16 * 1024 * 1024 });
        const markers: [RegExp, string][] = [
          [/Preparing to invoke AI/, 'prepare_ai'],
          [/Cache fetch for AI history/, 'fetch_ai_history'],
          [/Requesting full (chat )?history|requesting from client/, 'request_history'],
          [/Message history construction took/, 'history_constructed'],
          [/Failed to construct message history/, 'history_failed'],
          [/Active AI task .* exists/, 'active_task_queued'],
          [/Dispatching ai.ask in-process/, 'dispatch_started'],
          [/In-process ai.ask dispatch took/, 'dispatch_returned'],
          [/Failed to dispatch ai.ask/, 'dispatch_failed'],
          [/Message handler failed|Error in handle_message_received/, 'handler_failed'],
          [/Message handler completed/, 'handler_completed'],
        ];
        for (const line of output.split('\n')) {
          for (const [pattern, stage] of markers) if (pattern.test(line)) stages.push(stage);
        }
        return { events, stages, workerTaskStarts: (output.match(/TASK_STARTED/g) || []).length };
      } catch { stages.push('isolated_log_capture_unavailable'); }
    }
    return { events, stages };
  };
}

// contract-test: direct surface=cli assertions=maps-search.discovery.bounded-provider-routing
test('CLI rejects an invalid discovery area without a provider call', async () => {
  test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required');
  const result = await runCli(deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || ''), [
    'apps', 'maps', 'search', '--input', JSON.stringify({ requests: [{
      query: 'Ruins nearby', categories: ['ruins'], area: { latitude: 91, longitude: 13.405 },
    }] }), '--json',
  ], 30_000, { record: false });
  // The REST schema rejects the request before provider execution. The CLI
  // reports the real validation error and never labels it a successful search.
  const output = result.stdout + result.stderr;
  expect(result.code).not.toBe(0);
  expect(output).toMatch(/latitude|validation|422|invalid/i);
});

for (const fixture of ['maps_search_web', 'maps_discovery_web']) {
  // contract-test: direct surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.output.source-and-identity,maps-search.compatibility.regular-search
  test(`web chat renders ${fixture} parent, place cards and markers`, async ({ page }: { page: any }, testInfo: any) => {
    test.skip(!getTestAccount().email, 'Test account required');
    const log = createSignupLogger('maps-discovery-chat');
    const shot = createStepScreenshotter(log);
    const dispatch = captureDispatch(page);
    try {
      await loginToTestAccount(page, log, shot);
      await startNewChat(page, log);
      await waitForChatReady(page, log, 90_000);
      const discovery = fixture === 'maps_discovery_web';
      await sendMessage(page, withMockMarker(discovery ? 'Find ruins within 10 km of Berlin, Germany' : 'Find cafes in Berlin Mitte', fixture), log, shot, 'maps');
      const parent = await waitForEmbedFinished(page, 'maps', 'search');
      await expect(parent).toContainText(discovery ? 'Geoapify' : 'Google Maps');
      await expect(parent).toContainText(discovery ? '2 places' : '1 place');
      const fullscreen = await openFullscreen(page, parent);
      const cards = page.getByTestId('maps-place-card');
      await expect(cards).toHaveCount(discovery ? 2 : 1);
      await expect(cards.first()).toBeVisible();
      await expect(cards.first()).toContainText(discovery ? 'Ruine der Franziskaner-Klosterkirche' : 'OpenMates Fixture Cafe');
      await expect(page.getByTestId('embed-leaflet-map').last()).toHaveAttribute('data-map-ready', 'true');
      await expect(page.locator('.leaflet-marker-icon').first()).toBeVisible();
      if (discovery) {
        await expect(page.getByTestId('maps-place-source').first()).toHaveText('OpenStreetMap via Geoapify');
        await expect(page.getByTestId('maps-place-distance').first()).toHaveText('539 m');
      }
      await testInfo.attach(fixture, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
      await closeFullscreen(page, fullscreen);
      await deleteActiveChat(page, log, shot, 'maps');
    } finally {
      await testInfo.attach('maps-dispatch', {
        body: Buffer.from(JSON.stringify(dispatch(), null, 2)), contentType: 'application/json',
      });
    }
  });
}
