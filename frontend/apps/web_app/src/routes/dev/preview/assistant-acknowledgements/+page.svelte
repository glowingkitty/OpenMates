<!--
  Assistant acknowledgement audio preview.
  Loads the committed acknowledgement manifest at runtime so new languages,
  voice profiles, and clips appear without route changes.
  Lives under /dev/preview and relies on the shared /dev layout gate to block
  production access while keeping review controls available on dev deployments.
-->
<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';

	const MANIFEST_PATH = '/audio/assistant-acknowledgements/manifest.json';
	const AUDIO_BASE_PATH = '/audio/assistant-acknowledgements/';
	const CATEGORY_ORDER = ['general', 'lookup', 'reasoning', 'action'];
	const COLLATOR = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

	interface AcknowledgementClip {
		clip_id: string;
		voice_profile_id: string;
		voice_profile_version: number;
		language: string;
		request_category: string;
		variant: number;
		text: string;
		relative_path: string;
		sha256: string;
		duration_seconds: number;
	}

	interface AcknowledgementManifest {
		schema_version: number;
		provider: string;
		provider_model_id: string;
		clips: AcknowledgementClip[];
	}

	interface SelectOption {
		value: string;
		label: string;
		count: number;
	}

	interface ClipGroup {
		category: string;
		clips: AcknowledgementClip[];
	}

	let manifest = $state<AcknowledgementManifest | null>(null);
	let clips = $state<AcknowledgementClip[]>([]);
	let isLoading = $state(true);
	let loadError = $state<string | null>(null);
	let selectedLanguage = $state('');
	let selectedMate = $state('');
	let activeAudio: HTMLAudioElement | null = null;

	let languageOptions = $derived(buildLanguageOptions(clips));
	let mateOptions = $derived(buildMateOptions(clips, selectedLanguage));
	let selectedClips = $derived(filterSelectedClips(clips, selectedLanguage, selectedMate));
	let groupedClips = $derived(groupClips(selectedClips));
	let totalDuration = $derived(
		selectedClips.reduce((sum, clip) => sum + clip.duration_seconds, 0)
	);

	onMount(() => {
		void loadManifest();
	});

	async function loadManifest() {
		isLoading = true;
		loadError = null;

		try {
			const response = await fetch(MANIFEST_PATH, { cache: 'no-cache' });
			if (!response.ok) {
				throw new Error(`Manifest request failed with HTTP ${response.status}`);
			}

			const data = assertManifest(await response.json());
			manifest = data;
			clips = [...data.clips];
			selectInitialFilters(data.clips);
		} catch (error) {
			console.error('[AssistantAcknowledgementsPreview] Failed to load manifest:', error);
			loadError = error instanceof Error ? error.message : 'Failed to load acknowledgement manifest.';
		} finally {
			isLoading = false;
		}
	}

	function assertManifest(value: unknown): AcknowledgementManifest {
		if (!value || typeof value !== 'object') {
			throw new Error('Manifest is not an object.');
		}

		const candidate = value as Partial<AcknowledgementManifest>;
		if (!Array.isArray(candidate.clips)) {
			throw new Error('Manifest is missing a clips array.');
		}

		return candidate as AcknowledgementManifest;
	}

	function selectInitialFilters(sourceClips: AcknowledgementClip[]) {
		const requestedLanguage = page.url.searchParams.get('language');
		const requestedMate = page.url.searchParams.get('mate');
		const availableLanguages = buildLanguageOptions(sourceClips);
		const language = chooseOption(requestedLanguage, availableLanguages);
		const availableMates = buildMateOptions(sourceClips, language);

		selectedLanguage = language;
		selectedMate = chooseOption(requestedMate, availableMates);
	}

	function chooseOption(requested: string | null, options: SelectOption[]): string {
		if (requested && options.some((option) => option.value === requested)) {
			return requested;
		}

		return options[0]?.value ?? '';
	}

	function buildLanguageOptions(sourceClips: AcknowledgementClip[]): SelectOption[] {
		return buildOptions(sourceClips, (clip) => clip.language, (language) => language);
	}

	function buildMateOptions(sourceClips: AcknowledgementClip[], language: string): SelectOption[] {
		return buildOptions(
			sourceClips.filter((clip) => !language || clip.language === language),
			(clip) => clip.voice_profile_id,
			formatMateLabel
		);
	}

	function buildOptions(
		sourceClips: AcknowledgementClip[],
		getValue: (clip: AcknowledgementClip) => string,
		getLabel: (value: string) => string
	): SelectOption[] {
		const counts = new Map<string, number>();
		for (const clip of sourceClips) {
			const value = getValue(clip);
			counts.set(value, (counts.get(value) ?? 0) + 1);
		}

		return Array.from(counts, ([value, count]) => ({ value, label: getLabel(value), count })).sort(
			(a, b) => COLLATOR.compare(a.label, b.label)
		);
	}

	function filterSelectedClips(
		sourceClips: AcknowledgementClip[],
		language: string,
		mate: string
	): AcknowledgementClip[] {
		return sourceClips
			.filter((clip) => clip.language === language && clip.voice_profile_id === mate)
			.sort(compareClips);
	}

	function groupClips(sourceClips: AcknowledgementClip[]): ClipGroup[] {
		const groups = new Map<string, AcknowledgementClip[]>();
		for (const clip of sourceClips) {
			const group = groups.get(clip.request_category) ?? [];
			group.push(clip);
			groups.set(clip.request_category, group);
		}

		return Array.from(groups, ([category, categoryClips]) => ({
			category,
			clips: categoryClips.sort(compareClips)
		})).sort((a, b) => compareCategories(a.category, b.category));
	}

	function compareClips(a: AcknowledgementClip, b: AcknowledgementClip): number {
		const categoryComparison = compareCategories(a.request_category, b.request_category);
		if (categoryComparison !== 0) return categoryComparison;
		if (a.variant !== b.variant) return a.variant - b.variant;
		return COLLATOR.compare(a.clip_id, b.clip_id);
	}

	function compareCategories(a: string, b: string): number {
		const aIndex = CATEGORY_ORDER.indexOf(a);
		const bIndex = CATEGORY_ORDER.indexOf(b);
		if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
		if (aIndex !== -1) return -1;
		if (bIndex !== -1) return 1;
		return COLLATOR.compare(a, b);
	}

	function handleLanguageChange(event: Event) {
		selectedLanguage = (event.currentTarget as HTMLSelectElement).value;
		selectedMate = buildMateOptions(clips, selectedLanguage)[0]?.value ?? '';
		stopActiveAudio();
		updateQueryParams();
	}

	function handleMateChange(event: Event) {
		selectedMate = (event.currentTarget as HTMLSelectElement).value;
		stopActiveAudio();
		updateQueryParams();
	}

	function updateQueryParams() {
		const nextUrl = new URL(window.location.href);
		setOrDeleteQueryParam(nextUrl, 'language', selectedLanguage);
		setOrDeleteQueryParam(nextUrl, 'mate', selectedMate);
		replaceState(nextUrl, {});
	}

	function setOrDeleteQueryParam(url: URL, name: string, value: string) {
		if (value) {
			url.searchParams.set(name, value);
		} else {
			url.searchParams.delete(name);
		}
	}

	function handleAudioPlay(event: Event) {
		const audio = event.currentTarget as HTMLAudioElement;
		if (activeAudio && activeAudio !== audio) {
			stopAudio(activeAudio);
		}
		activeAudio = audio;
	}

	function stopActiveAudio() {
		if (activeAudio) {
			stopAudio(activeAudio);
			activeAudio = null;
		}
	}

	function stopAudio(audio: HTMLAudioElement) {
		audio.pause();
		try {
			audio.currentTime = 0;
		} catch (error) {
			console.warn('[AssistantAcknowledgementsPreview] Could not reset audio position:', error);
		}
	}

	function getAudioSrc(clip: AcknowledgementClip): string {
		return `${AUDIO_BASE_PATH}${clip.relative_path}`;
	}

	function formatMateLabel(value: string): string {
		return value
			.split(/[-_]/)
			.map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
			.join(' ');
	}

	function formatCategoryLabel(value: string): string {
		return value.replace(/[-_]/g, ' ');
	}

	function formatDuration(seconds: number): string {
		return `${seconds.toFixed(2)}s`;
	}

	function formatSha(value: string): string {
		return value.slice(0, 12);
	}
</script>

<svelte:head>
	<title>Assistant acknowledgement audio preview</title>
</svelte:head>

<main class="ack-page" data-testid="assistant-ack-preview-page">
	<div class="ack-shell">
		<header class="hero">
			<a class="back-link" href="/dev/preview">Back to preview index</a>
			<p class="eyebrow">Dev audio review</p>
			<h1>Assistant acknowledgements</h1>
			<p class="hero-copy">
				Review every committed assistant acknowledgement MP3 by language, mate, request category,
				and variant. The inventory is loaded from the static manifest at runtime.
			</p>
		</header>

		{#if isLoading}
			<section class="state-card" aria-live="polite" data-testid="assistant-ack-loading">
				<h2>Loading clips</h2>
				<p>Reading {MANIFEST_PATH}</p>
			</section>
		{:else if loadError}
			<section class="state-card state-card--error" role="alert" data-testid="assistant-ack-error">
				<h2>Manifest failed to load</h2>
				<p>{loadError}</p>
			</section>
		{:else}
			<section class="controls-card" aria-labelledby="filters-heading">
				<div class="controls-header">
					<div>
						<h2 id="filters-heading">Review filters</h2>
						<p>
							{clips.length} clips from {manifest?.provider} / {manifest?.provider_model_id}
						</p>
					</div>
					<p class="schema-pill">Manifest v{manifest?.schema_version}</p>
				</div>

				<div class="control-grid">
					<label class="field" for="language-select">
						<span>Language</span>
						<select
							id="language-select"
							bind:value={selectedLanguage}
							onchange={handleLanguageChange}
							data-testid="assistant-ack-language-select"
						>
							{#each languageOptions as option (option.value)}
								<option value={option.value}>{option.label} ({option.count} clips)</option>
							{/each}
						</select>
					</label>

					<label class="field" for="mate-select">
						<span>Mate</span>
						<select
							id="mate-select"
							bind:value={selectedMate}
							onchange={handleMateChange}
							data-testid="assistant-ack-mate-select"
						>
							{#each mateOptions as option (option.value)}
								<option value={option.value}>{option.label} ({option.count} clips)</option>
							{/each}
						</select>
					</label>
				</div>

				<p class="selection-summary" data-testid="assistant-ack-selection-summary">
					Showing {selectedClips.length} clips for {selectedLanguage} / {formatMateLabel(selectedMate)}
					with {formatDuration(totalDuration)} total audio.
				</p>
			</section>

			{#if groupedClips.length > 0}
				<div class="clip-groups" data-testid="assistant-ack-clip-groups">
					{#each groupedClips as group (group.category)}
						<section class="clip-group" aria-labelledby="category-{group.category}">
							<div class="group-header">
								<h2 id="category-{group.category}">{formatCategoryLabel(group.category)}</h2>
								<span>{group.clips.length} variants</span>
							</div>

							<div class="clip-list">
								{#each group.clips as clip (clip.clip_id)}
									<article class="clip-card" data-testid="assistant-ack-clip-card">
										<div class="clip-heading">
											<h3>Variant {clip.variant}</h3>
											<span>{formatDuration(clip.duration_seconds)}</span>
										</div>


										<p class="transcript-label">Transcript</p>
										<blockquote>{clip.text}</blockquote>

										<audio
											controls
											preload="metadata"
											src={getAudioSrc(clip)}
											onplay={handleAudioPlay}
											aria-label={`Play ${formatMateLabel(clip.voice_profile_id)} ${clip.language} ${clip.request_category} variant ${clip.variant}: ${clip.text}`}
										></audio>

										<dl class="metadata-grid">
											<div>
												<dt>Clip ID</dt>
												<dd>{clip.clip_id}</dd>
											</div>
											<div>
												<dt>Voice version</dt>
												<dd>{clip.voice_profile_version}</dd>
											</div>
											<div>
												<dt>Source</dt>
												<dd title={getAudioSrc(clip)}>{getAudioSrc(clip)}</dd>
											</div>
											<div>
												<dt>SHA-256</dt>
												<dd title={clip.sha256}>{formatSha(clip.sha256)}</dd>
											</div>
										</dl>
									</article>
								{/each}
							</div>
						</section>
					{/each}
				</div>
			{:else}
				<section class="state-card" data-testid="assistant-ack-empty">
					<h2>No clips match this selection</h2>
					<p>Choose another language or mate from the manifest-backed filters.</p>
				</section>
			{/if}
		{/if}
	</div>
</main>

<style>
	.ack-page {
		min-height: 100vh;
		background:
			radial-gradient(circle at top left, color-mix(in srgb, var(--color-primary-start) 18%, transparent), transparent 34rem),
			var(--color-grey-10);
		color: var(--color-font-primary);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.ack-shell {
		max-width: 70rem;
		margin: 0 auto;
		padding: 2rem 1.5rem 4rem;
	}

	.hero {
		display: grid;
		gap: 0.5rem;
		margin-bottom: 1.5rem;
	}

	.back-link {
		width: fit-content;
		color: var(--color-primary-start);
		font-size: var(--font-size-small);
		font-weight: 600;
		text-decoration: none;
	}

	.back-link:hover,
	.back-link:focus-visible {
		text-decoration: underline;
	}

	.eyebrow {
		margin: 0;
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	h1,
	h2,
	h3,
	p {
		margin-top: 0;
	}

	h1 {
		margin-bottom: 0;
		font-size: var(--font-size-h2);
		font-weight: 800;
	}

	.hero-copy {
		max-width: 44rem;
		margin-bottom: 0;
		color: var(--color-font-tertiary);
		font-size: var(--font-size-p);
		line-height: 1.5;
	}

	.controls-card,
	.state-card,
	.clip-group {
		border: 0.0625rem solid var(--color-grey-25);
		border-radius: var(--radius-6, 0.875rem);
		background: var(--color-grey-0);
		box-shadow: var(--shadow-sm);
	}

	.controls-card {
		display: grid;
		gap: 1rem;
		margin-bottom: 1.5rem;
		padding: 1.25rem;
	}

	.controls-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.controls-header h2,
	.group-header h2,
	.state-card h2 {
		margin-bottom: 0.25rem;
		font-size: var(--font-size-h3);
		font-weight: 700;
	}

	.controls-header p,
	.state-card p {
		margin-bottom: 0;
		color: var(--color-font-tertiary);
		font-size: var(--font-size-small);
	}

	.schema-pill {
		flex: 0 0 auto;
		margin: 0;
		padding: 0.35rem 0.75rem;
		border: 0.0625rem solid var(--color-grey-30);
		border-radius: var(--radius-full);
		background: var(--color-grey-20);
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xs);
		font-weight: 700;
	}

	.control-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1rem;
	}

	.field {
		display: grid;
		gap: 0.35rem;
		color: var(--color-font-primary);
		font-size: var(--font-size-small);
		font-weight: 700;
	}

	.field select {
		width: 100%;
		min-height: 2.75rem;
		padding: 0.75rem 1rem;
		border: 0.0625rem solid var(--color-grey-30);
		border-radius: var(--radius-8, 1.25rem);
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font: inherit;
		font-weight: 600;
	}

	.field select:focus-visible {
		border-color: var(--color-button-primary);
		outline: 0.1875rem solid color-mix(in srgb, var(--color-button-primary) 24%, transparent);
		outline-offset: 0.125rem;
	}

	.selection-summary {
		margin-bottom: 0;
		color: var(--color-font-tertiary);
		font-size: var(--font-size-small);
	}

	.clip-groups {
		display: grid;
		gap: 1.5rem;
	}

	.clip-group {
		padding: 1rem;
	}

	.group-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
		padding-bottom: 0.75rem;
		border-bottom: 0.0625rem solid var(--color-grey-25);
	}

	.group-header h2 {
		margin-bottom: 0;
		text-transform: capitalize;
	}

	.group-header span {
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xs);
		font-weight: 700;
	}

	.clip-list {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 1rem;
	}

	.clip-card {
		display: grid;
		gap: 0.85rem;
		padding: 1rem;
		border: 0.0625rem solid var(--color-grey-25);
		border-radius: var(--radius-5, 0.75rem);
		background: var(--color-grey-10);
	}

	.clip-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.clip-heading h3 {
		margin-bottom: 0;
		font-size: var(--font-size-h4);
		font-weight: 700;
	}

	.clip-heading span {
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xs);
		font-weight: 700;
	}

	.transcript-label {
		margin-bottom: -0.5rem;
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xxs);
		font-weight: 700;
	}

	blockquote {
		margin: 0;
		padding: 0.75rem;
		border-inline-start: 0.1875rem solid var(--color-primary-start);
		border-radius: var(--radius-3, 0.5rem);
		background: var(--color-grey-20);
		color: var(--color-font-primary);
		font-size: var(--font-size-small);
		line-height: 1.5;
		user-select: text;
	}

	audio {
		width: 100%;
	}

	.metadata-grid {
		display: grid;
		gap: 0.5rem;
		margin: 0;
	}

	.metadata-grid div {
		display: grid;
		gap: 0.15rem;
		min-width: 0;
	}

	dt {
		color: var(--color-font-tertiary);
		font-size: var(--font-size-xxs);
		font-weight: 700;
	}

	dd {
		margin: 0;
		overflow-wrap: anywhere;
		color: var(--color-font-primary);
		font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
		font-size: var(--font-size-xxs);
		line-height: 1.45;
		user-select: text;
	}

	.state-card {
		padding: 1.5rem;
	}

	.state-card--error {
		border-color: var(--color-error);
		background: var(--color-error-light);
	}

	.state-card--error h2,
	.state-card--error p {
		color: var(--color-error);
	}

	@media (max-width: 56rem) {
		.clip-list {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 45.625rem) {
		.ack-shell {
			padding: 1.25rem 1rem 3rem;
		}

		.controls-header,
		.group-header {
			align-items: stretch;
			flex-direction: column;
		}

		.control-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
