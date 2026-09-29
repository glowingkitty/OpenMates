const none = { executed: 0, passed: 0, failed: 0, skipped: 0 };

export default {
  daily: {
    date: '2026-09-28', status: 'blocked', finalization: 'final',
    areas: {
      unit: { executed: 6772, passed: 6600, failed: 172, skipped: 5 },
      sdk_cli: { executed: 71, passed: 70, failed: 1, skipped: 0 },
      web_e2e: none,
    },
    apple_e2e: { status: 'not_scheduled', counts: none },
    selected_specs: null, admitted_specs: 0, held_specs: null,
    signup: { executed: [], held: [], live_email: { status: 'failed' } },
  },
  reportHref: '/v1/status/tests/daily/2026-09-28?format=html',
};

export const variants = {
  Stale: {
    daily: {
      date: '2026-09-27', fresh: false, status: 'passed', finalization: 'final',
      areas: {
        unit: { executed: 6800, passed: 6800, failed: 0, skipped: 0 },
        sdk_cli: { executed: 71, passed: 71, failed: 0, skipped: 0 },
        web_e2e: { executed: 20, passed: 20, failed: 0, skipped: 0 },
      },
      apple_e2e: { status: 'passed', counts: { executed: 42, passed: 42, failed: 0, skipped: 0 } },
      selected_specs: 20, admitted_specs: 20, held_specs: 0,
      signup: { executed: [], held: [], live_email: { status: 'passed' } },
    },
    reportHref: '/v1/status/tests/daily/2026-09-27?format=html',
  },
  Passed: {
    daily: {
      date: '2026-09-29', status: 'passed', finalization: 'final',
      areas: {
        unit: { executed: 6800, passed: 6800, failed: 0, skipped: 0 },
        sdk_cli: { executed: 71, passed: 71, failed: 0, skipped: 0 },
        web_e2e: { executed: 930, passed: 930, failed: 0, skipped: 0 },
      },
      apple_e2e: { status: 'passed', counts: { executed: 42, passed: 42, failed: 0, skipped: 0 } },
      selected_specs: 281, admitted_specs: 281, held_specs: 0,
      signup: { executed: ['signup-2fa-reconnect-preview.spec.ts'], held: [], live_email: { status: 'passed' } },
    },
    reportHref: '/v1/status/tests/daily/2026-09-29?format=html',
  },
};
