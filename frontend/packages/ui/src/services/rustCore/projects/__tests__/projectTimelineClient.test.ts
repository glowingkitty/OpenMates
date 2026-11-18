// @vitest-environment node
/**
 * Page client of the `projectTimeline` unit (feature.projects): a read or
 * restore the unit refuses because the page's history session is still the
 * local-only admission asks once for the existing server-checked upgrade and
 * is sent again; any other refusal, a missing upgrade hook and a failed
 * upgrade keep the original refusal (the Timeline tab shows its error state).
 * The Worker and the admission are stubs.
 */
import { describe, expect, it, vi } from 'vitest';

import { SERVER_SESSION_TIMEOUT_MS, withServerSession } from '../projectTimelineClient';
import { UnitPortError } from '../../host/unitPort';

const PAGE = { entries: [], nextCursor: null };

describe('project timeline withServerSession', () => {
	// contract-test: direct surface=gui.web assertions=projects.history.native-commits
	it('upgrades a local-only session once and resends the refused request', async () => {
		const send = vi.fn().mockRejectedValueOnce(new UnitPortError('local_session')).mockResolvedValueOnce(PAGE);
		const ensure = vi.fn(async () => true);
		await expect(withServerSession(send, ensure)).resolves.toEqual(PAGE);
		expect(ensure).toHaveBeenCalledWith(SERVER_SESSION_TIMEOUT_MS);
		expect(send).toHaveBeenCalledTimes(2);
		const unbound = vi.fn().mockRejectedValueOnce(new UnitPortError('not_admitted')).mockResolvedValueOnce(PAGE);
		await expect(withServerSession(unbound, async () => true)).resolves.toEqual(PAGE);
	});

	// contract-test: direct surface=gui.web assertions=projects.history.native-commits
	it('keeps the refusal when the upgrade is missing, fails, or the resend is refused again', async () => {
		const refused = () => vi.fn().mockRejectedValue(new UnitPortError('local_session'));
		await expect(withServerSession(refused(), async () => false)).rejects.toMatchObject({ code: 'local_session' });
		await expect(withServerSession(refused(), async () => { throw new Error('session_expired'); }))
			.rejects.toMatchObject({ code: 'local_session' });
		const twice = refused();
		await expect(withServerSession(twice, async () => true)).rejects.toMatchObject({ code: 'local_session' });
		expect(twice).toHaveBeenCalledTimes(2);
	});

	// contract-test: direct surface=gui.web assertions=projects.history.native-commits
	it('never upgrades or resends for any other refusal', async () => {
		const send = vi.fn().mockRejectedValue(new UnitPortError('project_not_found'));
		const ensure = vi.fn(async () => true);
		await expect(withServerSession(send, ensure)).rejects.toMatchObject({ code: 'project_not_found' });
		expect(ensure).not.toHaveBeenCalled();
		expect(send).toHaveBeenCalledTimes(1);
	});
});
