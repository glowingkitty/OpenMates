// Status page API functions.
// Handles data fetching with lazy-loading support for detail endpoints.
// Architecture: docs/architecture/infrastructure/status-page.md

import { getApiEndpoint } from '@repo/ui';
import type { StatusSummary, HealthGroupDetail, TestSuiteDetail, IntraDayRunsResponse } from './types';

const BASE = '/v1/status';

/** Fetch summary-only status data (lightweight, used for 60s auto-refresh). */
export async function fetchSummary(): Promise<StatusSummary> {
	const res = await fetch(getApiEndpoint(BASE));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch detailed health data for a specific group (called on expand). */
export async function fetchGroupDetail(group: string): Promise<HealthGroupDetail> {
	const res = await fetch(getApiEndpoint(`${BASE}/health?group=${encodeURIComponent(group)}`));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch detailed test data for a suite, optionally filtered by category (called on expand). */
export async function fetchTestDetail(
	suite: string,
	category?: string
): Promise<TestSuiteDetail> {
	let url = `${BASE}/tests?suite=${encodeURIComponent(suite)}`;
	if (category) {
		url += `&category=${encodeURIComponent(category)}`;
	}
	const res = await fetch(getApiEndpoint(url));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}

/** Fetch all test runs for a specific date (intra-day sub-timeline). */
export async function fetchIntraDayRuns(date: string): Promise<IntraDayRunsResponse> {
	const res = await fetch(getApiEndpoint(`${BASE}/tests/runs?date=${encodeURIComponent(date)}`));
	if (!res.ok) throw new Error(`${res.status}`);
	return res.json();
}
