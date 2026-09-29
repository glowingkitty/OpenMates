<script lang="ts">
	type Counts = { executed: number; passed: number; failed: number; skipped: number };
	type Daily = {
		date: string;
		fresh?: boolean;
		status: string;
		finalization: string;
		areas: { unit: Counts; sdk_cli: Counts; web_e2e: Counts };
		apple_e2e: { status: string; counts: Counts };
		selected_specs: number | null;
		admitted_specs: number;
		held_specs: number | null;
		signup: { executed: string[]; held: string[]; live_email: { status: string } };
	};
	interface Props { daily: Daily; reportHref: string }
	let { daily, reportHref }: Props = $props();
	const formatCount = (count: number) => new Intl.NumberFormat('en-US').format(count);
	let rows = $derived([
		{ label: 'Unit suites', counts: daily.areas.unit, detail: '' },
		{ label: 'SDK and CLI', counts: daily.areas.sdk_cli, detail: '' },
		{ label: 'Web E2E', counts: daily.areas.web_e2e, detail: daily.selected_specs === null
			? 'Spec inventory unknown; selection did not finish'
			: `${daily.selected_specs} selected · ${daily.admitted_specs} admitted · ${daily.held_specs ?? 0} held` },
		{ label: 'Native Apple E2E', counts: daily.apple_e2e.counts,
			detail: daily.apple_e2e.status === 'not_scheduled' ? 'No scheduled native run' : daily.apple_e2e.status },
	]);
</script>

<section class="daily-digest" data-testid="daily-test-digest" aria-label="Nightly test results">
	<header>
		<div>
			<h2>Nightly tests · {daily.date}</h2>
			{#if daily.fresh === false}<p class="stale">Stale result: no report for the latest scheduled run</p>{/if}
			<p class="status" class:bad={daily.status !== 'passed'}>{daily.status.replaceAll('_', ' ').toUpperCase()}</p>
		</div>
		<a href={reportHref}>Full results</a>
	</header>
	<div class="rows">
		{#each rows as row (row.label)}
			<div class="row">
				<div class="row-heading"><strong>{row.label}</strong><span class:bad={row.counts.failed > 0}>{formatCount(row.counts.executed)} run · {formatCount(row.counts.failed)} failed</span></div>
				<p>{formatCount(row.counts.passed)} passed · {formatCount(row.counts.skipped)} skipped{row.detail ? ` · ${row.detail}` : ''}</p>
			</div>
		{/each}
	</div>
	<p class="signup">Signup: {daily.signup.executed.length} browser specs ran · {daily.signup.held.length} held · live email {daily.signup.live_email.status.replaceAll('_', ' ')}</p>
</section>

<style>
	.daily-digest { color: var(--color-font-primary, #e5e7eb); }
	header, .row-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; }
	header { padding-bottom: 0.5rem; border-bottom: 1px solid var(--color-grey-25, #52525b); }
	h2 { font-size: 0.95rem; margin: 0; }
	header a { color: var(--color-primary, #d6ac17); font-size: 0.8rem; flex: none; }
	.status { margin: 0.1rem 0 0; font-size: 0.78rem; font-weight: 700; color: var(--color-success, #22c55e); }
	.stale { margin: 0.2rem 0; color: var(--color-error, #ef4444); font-size: 0.78rem; }
	.bad, .status.bad { color: var(--color-error, #ef4444); }
	.row { padding: 0.5rem 0; border-bottom: 1px solid var(--color-grey-20, #3f3f46); }
	.row-heading { font-size: 0.85rem; }
	.row p, .signup { margin: 0.15rem 0 0; font-size: 0.76rem; color: var(--color-font-secondary, #a1a1aa); overflow-wrap: anywhere; }
	.signup { margin-top: 0.65rem; }
	@media (max-width: 430px) { .row-heading { align-items: flex-start; flex-direction: column; gap: 0.1rem; } }
</style>
