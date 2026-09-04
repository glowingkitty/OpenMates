/**
 * Deterministic props for the isolated MessageInput preview.
 * The default state mirrors the minimized unauthenticated composer.
 * Focus interactions reveal the expanded action row during component tests.
 * No callbacks in this fixture send messages or invoke backend actions.
 */
export default {
	showActionButtons: false
};
