/**
 * Status page TypeScript types (v3).
 * Compact layout: service groups, E2E test categories, response time charts, intra-day drill-down.
 * Architecture: docs/architecture/infrastructure/status-page.md
 * Tests: frontend/apps/web_app/tests/status-page.spec.ts
 */

export type ServiceStatus = 'operational' | 'degraded' | 'down' | 'unknown';

export type DayStatus = {
	date: string;
	status: ServiceStatus;
};

export type ResponseTimePoint = {
	timestamp: string;
	avg_ms: number;
	min_ms: number;
	max_ms: number;
	samples: number;
};

export type Service = {
	id: string;
	name: string;
	status: ServiceStatus;
	uptime_90d: DayStatus[];
	uptime_pct: number;
	response_times_7d: ResponseTimePoint[] | null;
};

export type ServiceGroupData = {
	name: string;
	services: Service[];
};

export type TestSpec = {
	name: string;
	status: 'passed' | 'failed';
	error: string | null;
	duration_s: number | null;
	timeline_30d: DayStatus[];
};

export type TestCategory = {
	name: string;
	total: number;
	passed: number;
	failed: number;
	specs: TestSpec[];
};

export type TestsData = {
	total: number;
	passed: number;
	failed: number;
	last_run: string | null;
	categories: TestCategory[];
};

export type IncidentUpdate = {
	status: string;
	timestamp: string;
};

export type Incident = {
	component: string;
	group: string;
	severity: string;
	started_at: string;
	resolved_at: string | null;
	duration_minutes: number | null;
	updates: IncidentUpdate[];
};

export type IntraDayCheck = {
	time: string;
	status: ServiceStatus;
	response_time_ms: number | null;
	error?: string;
};

export type IntraDayTestRun = {
	time: string;
	status: 'passed' | 'failed';
	duration_s: number | null;
	error: string | null;
};

export type StatusResponse = {
	status: ServiceStatus;
	last_updated: string;
	uptime_pct: number;
	groups: ServiceGroupData[];
	tests: TestsData;
	incidents: Incident[];
};
