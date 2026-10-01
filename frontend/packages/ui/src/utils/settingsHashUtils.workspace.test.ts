import { describe, expect, it } from 'vitest';

import {
  clearSettingsPathFromHash,
  setSettingsPathInHash,
  updateHashParams,
} from './settingsHashUtils';

describe('workspace settings hash state', () => {
  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it.each(['plans', 'projects', 'tasks', 'workflows'])(
    'preserves the %s workspace marker while settings opens and closes',
    (workspace) => {
      const withSettings = setSettingsPathInHash(`#${workspace}`, 'privacy/hide-personal-data');

      expect(withSettings).toBe(`#${workspace}&settings=privacy/hide-personal-data`);
      expect(clearSettingsPathFromHash(withSettings)).toBe(`#${workspace}`);
    },
  );

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding,settings-ui.shell.lifecycle-and-routing
  it.each(['#apps', '#apps/all&e2e-debug=trace', '#apps/health&tab=embeds'])(
    'preserves the Apps route %s while settings opens and closes',
    (hash) => {
      const withSettings = setSettingsPathInHash(hash, 'main');

      expect(withSettings).toBe(`${hash}&settings=main`);
      expect(clearSettingsPathFromHash(withSettings)).toBe(hash);
    },
  );

  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it('preserves a workspace marker while chat-only parameters are cleared', () => {
    expect(
      updateHashParams('#projects', {
        'chat-id': null,
        'message-id': null,
        'embed-id': null,
      }),
    ).toBe('#projects');
  });
});
