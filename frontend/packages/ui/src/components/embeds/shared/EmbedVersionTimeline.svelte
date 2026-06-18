<!--
  EmbedVersionTimeline — version history scrubber for diffable embeds.

  Shows a horizontal timeline of version dots with timestamps. Users can click
  any version to view the content at that point. Supports diff view toggle
  (show changes vs full content) and version restore.

  Used in: CodeEmbedFullscreen, DocsEmbedFullscreen, SheetEmbedFullscreen.
  Architecture: docs/architecture/messaging/embed-diff-editing.md
-->
<script lang="ts">
	import {
		fetchEmbedVersionContent,
		fetchEmbedVersions,
		getEmbedDiffs,
		restoreEmbedVersion,
		type EmbedVersionMeta
	} from '../../../services/embedDiffStore';

	interface Props {
		embedId: string;
		currentVersion: number;
		currentContent: string;
		buildRestoredContent?: (restoredContent: string, newVersion: number) => Record<string, unknown>;
		onVersionSelect: (version: number, content: string | null) => void;
	}

	let { embedId, currentVersion, currentContent, buildRestoredContent, onVersionSelect }: Props = $props();

	let versions: EmbedVersionMeta[] = $state([]);
	let selectedVersion: number = $state(0);
	let activeCurrentVersion: number = $state(0);
	let loading: boolean = $state(true);
	let loadingContent: boolean = $state(false);
	let restoring: boolean = $state(false);
	let readonly: boolean = $state(false);
	let errorMessage: string = $state('');
	let showChanges: boolean = $state(false);
	let selectedContent: string | null = $state(null);
	let restoreConfirmVersion: number | null = $state(null);
	let contentRequestId = 0;
	let selectedMeta = $derived(versions.find((version) => version.version_number === selectedVersion));
	let changeLines = $derived.by(() => buildLineDiff(selectedContent, currentContent));

	// Load version history on mount
	$effect(() => {
		loadVersions();
	});

	$effect(() => {
		selectedVersion = currentVersion;
		activeCurrentVersion = currentVersion;
	});

	async function loadVersions() {
		loading = true;
		errorMessage = '';
		try {
			const response = await fetchEmbedVersions(embedId);
			versions = response.versions;
			readonly = response.readonly;
			activeCurrentVersion = response.current_version;
		} catch (e) {
			console.warn('[EmbedVersionTimeline] Falling back to local versions:', e);
			const localVersions = await getEmbedDiffs(embedId);
			versions = localVersions.map((version) => ({
				version_number: version.version_number,
				created_at: version.created_at,
				has_snapshot: version.encrypted_snapshot !== undefined && version.encrypted_snapshot !== null,
				has_patch: version.encrypted_patch !== undefined && version.encrypted_patch !== null
			}));
			readonly = false;
			if (versions.length === 0) {
				errorMessage = e instanceof Error ? e.message : 'Failed to load versions';
			}
		}
		loading = false;
	}

	async function selectVersion(version: number) {
		const requestId = ++contentRequestId;
		selectedVersion = version;
		restoreConfirmVersion = null;
		errorMessage = '';
		if (version === activeCurrentVersion) {
			loadingContent = false;
			selectedContent = null;
			onVersionSelect(version, null);
			return;
		}
		selectedContent = null;
		loadingContent = true;
		try {
			const response = await fetchEmbedVersionContent(embedId, version);
			if (requestId !== contentRequestId) return;
			selectedContent = response.content;
			onVersionSelect(version, response.content);
		} catch (e) {
			if (requestId !== contentRequestId) return;
			errorMessage = e instanceof Error ? e.message : 'Failed to load version content';
			selectedContent = null;
			onVersionSelect(version, null);
		} finally {
			if (requestId === contentRequestId) loadingContent = false;
		}
	}

	async function restoreSelectedVersion() {
		if (selectedVersion === activeCurrentVersion || readonly || !buildRestoredContent) return;
		if (restoreConfirmVersion !== selectedVersion) {
			restoreConfirmVersion = selectedVersion;
			return;
		}
		restoring = true;
		errorMessage = '';
		try {
			const response = await restoreEmbedVersion(embedId, selectedVersion, {
				currentVersion: activeCurrentVersion,
				currentContent,
				buildRestoredContent
			});
			activeCurrentVersion = response.version_number;
			selectedVersion = response.version_number;
			selectedContent = response.content;
			restoreConfirmVersion = null;
			onVersionSelect(response.version_number, response.content);
			await loadVersions();
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'Failed to restore version';
		} finally {
			restoring = false;
		}
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

	function buildLineDiff(previous: string | null, current: string): Array<{ type: 'same' | 'added' | 'removed'; text: string }> {
		if (previous === null || selectedVersion === activeCurrentVersion) return [];
		const previousLines = previous.split('\n');
		const currentLines = current.split('\n');
		const rows: Array<{ type: 'same' | 'added' | 'removed'; text: string }> = [];
		const max = Math.max(previousLines.length, currentLines.length);
		for (let index = 0; index < max; index += 1) {
			const previousLine = previousLines[index];
			const currentLine = currentLines[index];
			if (previousLine === currentLine) {
				if (previousLine !== undefined) rows.push({ type: 'same', text: previousLine });
				continue;
			}
			if (previousLine !== undefined) rows.push({ type: 'removed', text: previousLine });
			if (currentLine !== undefined) rows.push({ type: 'added', text: currentLine });
		}
		return rows;
	}
</script>

{#if loading}
	<div class="version-timeline" data-testid="embed-version-timeline-loading">Loading version history...</div>
{:else if versions.length <= 1}
	<div class="version-timeline" data-testid="embed-version-timeline-empty">
		{errorMessage || 'No version history available yet.'}
	</div>
{:else}
	<div class="version-timeline" data-testid="embed-version-timeline">
		<div class="timeline-header">
			<span class="timeline-label">Version history</span>
			<span class="version-count">{versions.length} versions</span>
		</div>

		<div class="timeline-track">
			{#each versions as version, idx}
				{@const isSelected = version.version_number === selectedVersion}
				{@const isCurrent = version.version_number === activeCurrentVersion}
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
				{#if selectedMeta}
					{formatTimestamp(selectedMeta.created_at)}
				{/if}
				{#if loadingContent}
					 · Loading content...
				{/if}
			</span>
			{#if selectedVersion !== activeCurrentVersion && selectedContent !== null}
				<button
					class="changes-btn"
					data-testid="embed-version-changes-toggle"
					onclick={() => (showChanges = !showChanges)}
				>
					{showChanges ? 'Hide changes' : 'Show changes'}
				</button>
			{/if}
			{#if selectedVersion !== activeCurrentVersion && !readonly && buildRestoredContent}
				<button
					class="restore-btn"
					data-testid="restore-version-btn"
					disabled={restoring}
					onclick={restoreSelectedVersion}
				>
					{restoring
						? 'Restoring...'
						: restoreConfirmVersion === selectedVersion
							? `Confirm restore v${selectedVersion}`
							: `Restore v${selectedVersion}`}
				</button>
			{/if}
		</div>

		{#if showChanges && changeLines.length > 0}
			<pre class="changes-view" data-testid="embed-version-changes-view">{#each changeLines as line}<span class:added={line.type === 'added'} class:removed={line.type === 'removed'}>{line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}{line.text}</span>{/each}</pre>
		{/if}

		{#if readonly}
			<div class="timeline-note" data-testid="embed-version-readonly">Read-only shared history</div>
		{/if}
		{#if errorMessage}
			<div class="timeline-error" data-testid="embed-version-error">{errorMessage}</div>
		{/if}
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

	.restore-btn,
	.changes-btn {
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

	.restore-btn:hover,
	.changes-btn:hover {
		background: var(--color-button-primary, #6366f1);
		color: white;
	}

	.changes-view {
		margin-top: 8px;
		padding: 8px;
		max-height: 180px;
		overflow: auto;
		border-radius: 6px;
		background: var(--color-grey-0, #fff);
		border: 1px solid var(--color-grey-20, #e8e8e8);
		font-size: 11px;
		line-height: 1.45;
		white-space: pre-wrap;
	}

	.changes-view span {
		display: block;
	}

	.changes-view .added {
		color: var(--color-success, #10b981);
	}

	.changes-view .removed {
		color: var(--color-error, #dc2626);
	}

	.restore-btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}

	.timeline-note,
	.timeline-error {
		margin-top: 6px;
		font-size: 11px;
	}

	.timeline-note {
		color: var(--color-font-tertiary, #888);
	}

	.timeline-error {
		color: var(--color-error, #dc2626);
	}
</style>
