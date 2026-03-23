// Status page TypeScript types (v2).
// Three sections: Services (infrastructure), Apps (expandable), Functionalities (test-based).
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

// ─── Services section (flat infrastructure) ─────────────────────────────────

export type InfraService = {
	id: string;
	display_name: string;
	status: string;
	timeline_30d: TimelineEntry[];
};

// ─── Apps section (expandable) ──────────────────────────────────────────────

export type AppSummary = {
	id: string;
	display_name: string;
	status: string;
	timeline_30d: TimelineEntry[];
	provider_count: number;
	skill_count: number;
};

export type ProviderDetail = {
	id: string;
	name: string;
	status: string;
	timeline_30d: TimelineEntry[];
	error_message?: string;
	response_time_ms?: Record<string, number>;
	last_check?: string;
};

export type SkillDetail = {
	id: string;
	status: string;
	providers: { name: string; status: string }[];
};

export type AppDetail = AppSummary & {
	providers: ProviderDetail[];
	skills: SkillDetail[];
	api?: Record<string, unknown>;
	worker?: Record<string, unknown>;
	last_check?: string;
};

// ─── Functionalities section (test-based) ───────────────────────────────────

export type FunctionalitySummary = {
	name: string;
	status: string;
	pass_rate: number;
	total: number;
	passed: number;
	failed: number;
	timeline_30d: TimelineEntry[];
};

export type FunctionalityTest = {
	name: string;
	file: string;
	status: string;
	error?: string;
	last_run?: string;
	history_30d?: TimelineEntry[];
	sub_category?: string;
};

export type FunctionalitySubCategory = {
	name: string;
	status: string;
	pass_rate: number;
	total: number;
	passed: number;
	failed: number;
	timeline_30d: TimelineEntry[];
};

export type FunctionalityDetail = FunctionalitySummary & {
	tests: FunctionalityTest[];
	sub_categories?: FunctionalitySubCategory[] | null;
};

// ─── Intra-day hourly timeline ──────────────────────────────────────────────

export type IntraDayRun = {
	run_id: string;
	timestamp: string;
	duration_seconds: number;
	git_sha: string;
	summary: {
		total: number;
		passed: number;
		failed: number;
		skipped: number;
	};
	status: string;
};

export type IntraDayHour = {
	hour: number;
	run_count: number;
	summary: {
		total: number;
		passed: number;
		failed: number;
		skipped: number;
	};
	runs: IntraDayRun[];
};

export type IntraDayResponse = {
	date: string;
	source?: string | null;
	id?: string | null;
	hours: IntraDayHour[];
};

// ─── Current issues ─────────────────────────────────────────────────────────

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

// ─── Top-level status summary ───────────────────────────────────────────────

export type StatusSummary = {
	overall_status: string;
	last_updated: string;
	is_admin: boolean;
	overall_timeline_30d?: TimelineEntry[];
	services?: InfraService[];
	apps?: AppSummary[];
	functionalities?: FunctionalitySummary[];
	incidents?: { total_last_30d: number };
	current_issues?: {
		services: ServiceIssue[];
		services_total: number;
		failed_tests: TestIssue[];
		failed_tests_total: number;
	};
};
