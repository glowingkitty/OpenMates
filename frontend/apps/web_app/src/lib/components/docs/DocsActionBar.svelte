<script lang="ts">
	/**
	 * DocsActionBar — floating action buttons for docs pages.
	 *
	 * Provides share (copy URL), download as PDF, and report issue buttons.
	 * Positioned at top-right of the docs content area, matching ActiveChat's
	 * top-button pattern.
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 */
	import { text, notificationStore, settingsDeepLink, panelState } from '@repo/ui';
	import { tick } from 'svelte';

	interface Props {
		title: string;
	}

	let { title }: Props = $props();

	async function handleShare() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			notificationStore.success($text('documentation.actions.share_copied'), 2000);
		} catch {
			// Fallback for browsers that don't support clipboard API
			const input = document.createElement('input');
			input.value = window.location.href;
			document.body.appendChild(input);
			input.select();
			document.execCommand('copy');
			document.body.removeChild(input);
			notificationStore.success($text('documentation.actions.share_copied'), 2000);
		}
	}

	function handleDownloadPdf() {
		window.print();
	}

	async function handleReportIssue() {
		panelState.openSettings();
		await tick();
		await new Promise(resolve => setTimeout(resolve, 100));
		settingsDeepLink.set('report_issue');
	}
</script>

<div class="docs-action-bar">
	<button
		class="action-btn"
		title={$text('documentation.actions.share')}
		onclick={handleShare}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
			<polyline points="16 6 12 2 8 6" />
			<line x1="12" y1="2" x2="12" y2="15" />
		</svg>
	</button>
	<button
		class="action-btn"
		title={$text('documentation.actions.download_pdf')}
		onclick={handleDownloadPdf}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
			<polyline points="7 10 12 15 17 10" />
			<line x1="12" y1="15" x2="12" y2="3" />
		</svg>
	</button>
	<button
		class="action-btn"
		title={$text('documentation.actions.report_issue')}
		onclick={handleReportIssue}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<circle cx="12" cy="12" r="10" />
			<line x1="12" y1="8" x2="12" y2="12" />
			<line x1="12" y1="16" x2="12.01" y2="16" />
		</svg>
	</button>
</div>

<style>
	.docs-action-bar {
		position: absolute;
		top: 12px;
		inset-inline-end: 12px;
		z-index: 5;
		display: flex;
		gap: 4px;
		padding: 4px;
		border-radius: 10px;
		background-color: color-mix(in srgb, var(--color-grey-20) 80%, transparent);
		backdrop-filter: blur(8px);
		-webkit-backdrop-filter: blur(8px);
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: 8px;
		background: none;
		color: var(--color-font-secondary);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.action-btn:hover {
		background-color: var(--color-grey-30);
		color: var(--color-font-primary);
	}

	/* Hide action bar in print mode */
	@media print {
		.docs-action-bar {
			display: none;
		}
	}

	/* Mobile: smaller buttons */
	@media (max-width: 600px) {
		.docs-action-bar {
			top: 8px;
			inset-inline-end: 8px;
		}

		.action-btn {
			width: 28px;
			height: 28px;
		}

		.action-btn svg {
			width: 14px;
			height: 14px;
		}
	}
</style>
