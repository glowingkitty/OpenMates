<!--
  EmbedVersionTimeline — version history scrubber for diffable embeds.

  Shows a horizontal timeline of version dots with timestamps. Users can click
  any version to view the content at that point. Supports diff view toggle
  (show changes vs full content) and version restore.

  Used in: CodeEmbedFullscreen, DocsEmbedFullscreen, SheetEmbedFullscreen.
  Architecture: docs/architecture/messaging/embed-diff-editing.md
-->
<script lang="ts">
	import { getEmbedDiffs, type EmbedDiffRow } from '../../../services/embedDiffStore';
	import { t } from '../../../i18n/i18n';

	interface Props {
		embedId: string;
		currentVersion: number;
		onVersionSelect: (version: number, content: string | null) => void;
	}

	let { embedId, currentVersion, onVersionSelect }: Props = $props();

	let versions: EmbedDiffRow[] = $state([]);
	let selectedVersion: number = $state(currentVersion);
	let loading: boolean = $state(true);
	let showDiffView: boolean = $state(false);

	// Load version history on mount
	$effect(() => {
		loadVersions();
	});

	async function loadVersions() {
		loading = true;
		try {
			versions = await getEmbedDiffs(embedId);
		} catch (e) {
			console.error('[EmbedVersionTimeline] Failed to load versions:', e);
			versions = [];
		}
		loading = false;
	}

	function selectVersion(version: number) {
		selectedVersion = version;
		// For now, pass null — the parent component handles reconstruction
		// via the WebSocket request_embed_version event
		onVersionSelect(version, null);
	}

	function formatTimestamp(ts: number): string {
		const date = new Date(ts * 1000);
		const now = new Date();
		const diffMs = now.getTime() - date.getTime();
		const diffMin = Math.floor(diffMs / 60000);

		if (diffMin < 1) return 'just now';
		if (diffMin < 60) return `${diffMin}m ago`;
		if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
		return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}
</script>

{#if !loading && versions.length > 1}
	<div class="version-timeline" data-testid="embed-version-timeline">
		<div class="timeline-header">
			<span class="timeline-label">Version history</span>
			<span class="version-count">{versions.length} versions</span>
		</div>

		<div class="timeline-track">
			{#each versions as version, idx}
				{@const isSelected = version.version_number === selectedVersion}
				{@const isCurrent = version.version_number === currentVersion}
				<button
					class="version-dot"
					class:selected={isSelected}
					class:current={isCurrent}
					data-testid="version-dot-{version.version_number}"
					onclick={() => selectVersion(version.version_number)}
					title="v{version.version_number} — {formatTimestamp(version.created_at)}"
				>
					<span class="dot"></span>
					{#if isSelected}
						<span class="version-label">v{version.version_number}</span>
					{/if}
				</button>
				{#if idx < versions.length - 1}
					<span class="track-line"></span>
				{/if}
			{/each}
		</div>

		<div class="timeline-footer">
			<span class="timestamp">
				{#if versions[selectedVersion - 1]}
					{formatTimestamp(versions[selectedVersion - 1].created_at)}
				{/if}
			</span>
			{#if selectedVersion !== currentVersion}
				<button
					class="restore-btn"
					data-testid="restore-version-btn"
					onclick={() => onVersionSelect(selectedVersion, null)}
				>
					Restore v{selectedVersion}
				</button>
			{/if}
		</div>
	</div>
{/if}

<style>
	.version-timeline {
		padding: 12px 16px;
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
		background: var(--color-grey-5, #fafafa);
	}

	.timeline-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 10px;
	}

	.timeline-label {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-font-secondary, #555);
	}

	.version-count {
		font-size: 11px;
		color: var(--color-font-tertiary, #888);
	}

	.timeline-track {
		display: flex;
		align-items: center;
		gap: 0;
		padding: 4px 0;
	}

	.version-dot {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 4px 8px;
		border: none;
		background: none;
		cursor: pointer;
		position: relative;
	}

	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--color-grey-30, #ccc);
		transition: all 0.15s ease;
	}

	.version-dot:hover .dot {
		background: var(--color-button-primary, #6366f1);
		transform: scale(1.2);
	}

	.version-dot.selected .dot {
		background: var(--color-button-primary, #6366f1);
		box-shadow: 0 0 0 3px var(--color-button-primary-alpha-20, rgba(99, 102, 241, 0.2));
	}

	.version-dot.current .dot {
		background: var(--color-success, #10b981);
	}

	.version-dot.current.selected .dot {
		background: var(--color-success, #10b981);
		box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
	}

	.version-label {
		font-size: 10px;
		color: var(--color-button-primary, #6366f1);
		font-weight: 500;
		white-space: nowrap;
	}

	.track-line {
		flex: 1;
		height: 2px;
		min-width: 12px;
		background: var(--color-grey-25, #ddd);
	}

	.timeline-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 8px;
	}

	.timestamp {
		font-size: 11px;
		color: var(--color-font-tertiary, #888);
	}

	.restore-btn {
		font-size: 11px;
		font-weight: 500;
		padding: 4px 10px;
		border-radius: 6px;
		border: 1px solid var(--color-button-primary, #6366f1);
		background: transparent;
		color: var(--color-button-primary, #6366f1);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.restore-btn:hover {
		background: var(--color-button-primary, #6366f1);
		color: white;
	}
</style>
