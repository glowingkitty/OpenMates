// View glue of message-scoped image versions: the badge text and the version a
// fullscreen opens at.
import { describe, expect, it } from 'vitest';
import { rememberFullscreenVersion, takeFullscreenVersion, versionBadgeLabel } from '../imageVersionScope';

describe('imageVersionScope', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('labels a card only when the image has more than one version', () => {
		expect(versionBadgeLabel(2, 3)).toBe('v2');
		expect(versionBadgeLabel(1, 1)).toBeNull();
		expect(versionBadgeLabel(undefined, 3)).toBeNull();
		expect(versionBadgeLabel(1, undefined)).toBeNull();
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('opens fullscreen once at the version the card showed', () => {
		rememberFullscreenVersion('embed-1', 2);
		expect(takeFullscreenVersion('embed-1')).toBe(2);
		expect(takeFullscreenVersion('embed-1')).toBeUndefined();
		rememberFullscreenVersion('embed-1', 2);
		rememberFullscreenVersion('embed-1', undefined);
		expect(takeFullscreenVersion('embed-1')).toBeUndefined();
		expect(takeFullscreenVersion(undefined)).toBeUndefined();
	});
});
