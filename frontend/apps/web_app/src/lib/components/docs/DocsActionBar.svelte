<script lang="ts">
	/**
	 * DocsActionBar — top action buttons for docs pages.
	 *
	 * Reuses the same left-buttons > new-chat-button-wrapper pattern from
	 * ActiveChat.svelte for design consistency. Provides share (copy URL),
	 * download as PDF, and report issue buttons.
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

<div class="top-buttons">
	<div class="left-buttons">
		<div class="new-chat-button-wrapper">
			<button
				class="clickable-icon icon_share top-button"
				title={$text('documentation.actions.share')}
				onclick={handleShare}
			></button>
		</div>
		<div class="new-chat-button-wrapper">
			<button
				class="clickable-icon icon_download top-button"
				title={$text('documentation.actions.download_pdf')}
				onclick={handleDownloadPdf}
			></button>
		</div>
		<div class="new-chat-button-wrapper">
			<button
				class="clickable-icon icon_bug top-button"
				title={$text('documentation.actions.report_issue')}
				onclick={handleReportIssue}
			></button>
		</div>
	</div>
</div>

<style>
	/* Reuses ActiveChat's top-buttons / left-buttons / new-chat-button-wrapper pattern */
	.top-buttons {
		position: absolute;
		top: 15px;
		inset-inline-start: 15px;
		display: flex;
		z-index: 5;
	}

	.left-buttons {
		display: flex;
		gap: 10px;
	}

	.new-chat-button-wrapper {
		background-color: var(--color-grey-10);
		border-radius: 40px;
		padding: 8px;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
		display: flex;
		align-items: center;
		justify-content: center;
		transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
		cursor: pointer;
	}

	.new-chat-button-wrapper:hover {
		transform: scale(1.08);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
	}

	.new-chat-button-wrapper:active {
		transform: scale(0.95);
		box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
	}

	/* Mobile: smaller position offset */
	@media (max-width: 730px) {
		.top-buttons {
			top: 10px;
			inset-inline-start: 10px;
		}
	}

	/* Hide in print mode */
	@media print {
		.top-buttons {
			display: none;
		}
	}
</style>
