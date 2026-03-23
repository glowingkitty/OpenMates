// Status page API functions (v2).
// Handles data fetching with lazy-loading for detail endpoints.
// Architecture: docs/architecture/infrastructure/status-page.md

import { getApiEndpoint } from '@repo/ui';
import type { StatusSummary, AppDetail, FunctionalityDetail, IntraDayResponse } from './types';

const BASE = '/v1/status';

/** Fetch the full status page initial payload. */
export async function fetchSummary(): Promise<StatusSummary> {
	const res = await fetch(getApiEndpoint(BASE));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch detailed app data — providers + skills (called on expand). */
export async function fetchAppDetail(appId: string): Promise<AppDetail> {
	const res = await fetch(getApiEndpoint(`${BASE}/apps?app=${encodeURIComponent(appId)}`));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch detailed functionality data — sub-categories + tests (called on expand). */
export async function fetchFunctionalityDetail(name: string): Promise<FunctionalityDetail> {
	const res = await fetch(
		getApiEndpoint(`${BASE}/functionalities?name=${encodeURIComponent(name)}`)
	);
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch hourly-grouped intra-day data for any timeline (called on day click). */
export async function fetchIntraDayData(
	date: string,
	source?: string,
	id?: string
): Promise<IntraDayResponse> {
	let url = `${BASE}/timeline/intraday?date=${encodeURIComponent(date)}`;
	if (source) url += `&source=${encodeURIComponent(source)}`;
	if (id) url += `&id=${encodeURIComponent(id)}`;
	const res = await fetch(getApiEndpoint(url));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch all current issues (untruncated) for the expand view. */
export async function fetchAllIssues(): Promise<StatusSummary> {
	const res = await fetch(getApiEndpoint(`${BASE}?detail=summary`));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}
