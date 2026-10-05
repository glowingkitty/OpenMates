/**
 * Deterministic props for the isolated MessageInput preview.
 * The default state mirrors the minimized unauthenticated composer.
 * Focus interactions reveal the expanded action row during component tests.
 * No callbacks in this fixture send messages or invoke backend actions.
 */
export default {
	showActionButtons: false
};

export const variants = {
  projectSpecialist: {
    showActionButtons: false,
    activeFocusId: 'code-debugging',
    activeFocusAppId: 'code',
    activeProjectFocusName: 'OpenMates',
    activeSpecialistFocusName: 'Debugging',
    onFocusPillDeepLink: () => {},
    onFocusPillDeactivate: () => {},
  },
  longProjectSpecialist: {
    showActionButtons: false,
    activeFocusId: 'project-focus:11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222',
    activeProjectFocusName: 'A very long Project title for a narrow phone screen',
    activeSpecialistFocusName: 'Investigating a complicated application failure',
    onFocusPillDeepLink: () => {},
    onFocusPillDeactivate: () => {},
  },
};
