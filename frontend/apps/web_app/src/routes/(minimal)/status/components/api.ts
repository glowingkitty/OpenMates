/**
 * Status page API client (v3).
 * Fetches from core API /v1/status/v2 endpoints.
 * Architecture: docs/architecture/infrastructure/status-page.md
 */

import { getApiEndpoint } from '@repo/ui';
import type { StatusResponse, IntraDayCheck, IntraDayTestRun } from './types';

const BASE_PATH = '/v1/status/v2';

export async function fetchStatus(): Promise<StatusResponse> {
	const res = await fetch(getApiEndpoint(BASE_PATH));
	if (!res.ok) throw new Error(`Status API error: ${res.status}`);
	return res.json();
}

export async function fetchIntraDay(
	type: 'service' | 'test',
	id: string,
	date: string
): Promise<{ checks?: IntraDayCheck[]; runs?: IntraDayTestRun[] }> {
	const params = new URLSearchParams({ type, id, date });
	const res = await fetch(getApiEndpoint(`${BASE_PATH}/intraday?${params}`));
	if (!res.ok) throw new Error(`Intraday API error: ${res.status}`);
	return res.json();
}
