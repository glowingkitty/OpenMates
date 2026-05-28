/**
 * Client helpers for the dev-only Playwright recording browser.
 *
 * Fetches latest recording manifests from the API and keeps the route pages
 * focused on rendering videos, screenshots, and timestamped steps. The API
 * returns short-lived presigned URLs for private S3 objects.
 */
import { getApiEndpoint } from '@repo/ui';

export type TestRecordingAssetUrls = {
	video_url?: string | null;
	thumbnail_url?: string | null;
	report_url?: string | null;
	screenshot_urls?: Array<string | null>;
};

export type TestRecordingSummary = {
	spec: string;
	slug: string;
	title: string;
	status: string;
	run_id: string;
	duration_seconds?: number;
	error?: string | null;
	assets: TestRecordingAssetUrls;
};

export type TestRecordingStep = {
	index: number;
	type: string;
	title: string;
	timestamp?: string | null;
	video_time_seconds?: number | null;
	duration_seconds?: number | null;
	status?: string | null;
	error?: string | null;
	screenshot_url?: string | null;
};

export type TestRecordingDetail = TestRecordingSummary & {
	git_sha?: string;
	git_branch?: string;
	github_run_url?: string | null;
	steps: TestRecordingStep[];
};

export type TestRecordingsIndex = {
	run_id: string | null;
	git_sha: string | null;
	git_branch: string | null;
	generated_at?: string;
	tests: TestRecordingSummary[];
};

const TEST_RECORDINGS_PATH = '/v1/test-recordings';

export async function fetchTestRecordings(): Promise<TestRecordingsIndex> {
	const response = await fetch(getApiEndpoint(TEST_RECORDINGS_PATH));
	if (!response.ok) {
		throw new Error(`Test recordings API error: ${response.status}`);
	}
	return response.json();
}

export async function fetchTestRecording(slug: string): Promise<TestRecordingDetail> {
	const response = await fetch(getApiEndpoint(`${TEST_RECORDINGS_PATH}/${encodeURIComponent(slug)}`));
	if (!response.ok) {
		throw new Error(`Test recording API error: ${response.status}`);
	}
	return response.json();
}

export function formatDuration(seconds?: number | null): string {
	if (!seconds || seconds <= 0) return 'Unknown duration';
	if (seconds < 60) return `${Math.round(seconds)}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = Math.round(seconds % 60);
	return `${minutes}m ${rest}s`;
}

export function formatVideoTime(seconds?: number | null): string {
	if (seconds == null) return '--:--';
	const safeSeconds = Math.max(0, Math.round(seconds));
	const minutes = Math.floor(safeSeconds / 60);
	const rest = safeSeconds % 60;
	return `${minutes}:${String(rest).padStart(2, '0')}`;
}
