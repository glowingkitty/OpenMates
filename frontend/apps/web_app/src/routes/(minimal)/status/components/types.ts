// Status page TypeScript types.
// Shared across all status page components.
// Architecture: docs/architecture/infrastructure/status-page.md

export type TimelineStatus =
	| 'operational'
	| 'degraded'
	| 'down'
	| 'unknown'
	| 'passed'
	| 'failed'
	| 'not_run';

export type TimelineEntry = {
	date: string;
	status?: TimelineStatus;
	pass_rate?: number;
	tone?: number | null;
	passed?: number;
	failed?: number;
	total?: number;
	not_run?: number;
	has_run?: boolean;
	run_at?: string | null;
};

export type SelectedTimeline = {
	key: string;
	date: string;
	text: string;
};

export type HealthGroup = {
	group_name: string;
	display_name: string;
	status: string;
	service_count: number;
	timeline_30d: TimelineEntry[];
};

export type Service = {
	id: string;
	name: string;
	status: string;
	timeline_30d: TimelineEntry[];
	error_message?: string;
	response_time_ms?: Record<string, number>;
	last_check?: string;
	api?: Record<string, unknown>;
	worker?: Record<string, unknown>;
};

export type HealthGroupDetail = HealthGroup & {
	services: Service[];
};

export type TestSuiteData = {
	name: string;
	total: number;
	passed: number;
	failed: number;
	skipped: number;
	timeline_30d: TimelineEntry[];
};

export type TestData = {
	name: string;
	file?: string;
	status: string;
	error?: string;
	last_run?: string;
	history_30d?: TimelineEntry[];
	run_id?: string;
};

export type TestCategory = {
	total: number;
	passed: number;
	failed: number;
	pass_rate: number;
	history?: TimelineEntry[];
	tests?: TestData[];
};

export type TestSuiteDetail = {
	run_id: string | null;
	suites: Record<
		string,
		{
			total: number;
			passed: number;
			failed: number;
			tests: TestData[];
		}
	>;
	categories: Record<string, TestCategory>;
	flaky_tests: TestData[];
};

export type ServiceIssue = {
	service_type: string;
	service_id: string;
	name: string;
	group: string;
	status: string;
	error_message?: string;
	last_check?: string;
};

export type TestIssue = {
	suite: string;
	name: string;
	file: string;
	error?: string;
};

export type StatusSummary = {
	overall_status: string;
	last_updated: string;
	is_admin: boolean;
	overall_timeline_30d?: TimelineEntry[];
	health?: { groups: HealthGroup[] };
	tests?: {
		overall_status: string;
		latest_run: { summary: Record<string, number>; timestamp: string } | null;
		suites: TestSuiteData[];
		trend: TimelineEntry[];
	};
	incidents?: { total_last_30d: number };
	current_issues?: {
		services: ServiceIssue[];
		failed_tests: TestIssue[];
	};
};
