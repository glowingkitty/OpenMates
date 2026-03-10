<!--
  Embed App Showcase Page.
  Shows ALL embed display types for a given app on a single scrollable page.

  URL: /dev/preview/embeds/<app>
  Examples:
    /dev/preview/embeds/code    → all code embed types
    /dev/preview/embeds/web     → all web embed types
    /dev/preview/embeds/travel  → all travel embed types

  Display types shown per skill section:
    1. Inline Link         (simulated — EmbedInlineLink needs live embedStore)
    2. Quote Block         (simulated — SourceQuoteBlock needs live embedStore)
    3. Preview — Mobile    (isMobile=true  → 150×290px)
    4. Preview — Small     (isMobile=false → 300×200px)
    5. Preview — Large     (inside container-type:inline-size "embed-preview" >300px → full-width×400px)
    6. Fullscreen          (clipped inline via isolation:isolate + overflow:hidden)

  Props: loaded from each skill's .preview.ts companion file.
  Templates: .preview.ts variants become template buttons per section.
  Custom JSON editor: collapsible per-section props override panel.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { mount, unmount } from 'svelte';
	import { theme } from '@repo/ui';

	// ─── App Registry ─────────────────────────────────────────────────────────

	interface EmbedSection {
		skillLabel: string;
		appId: string;
		previewPath: string;
		fullscreenPath: string;
		inlineLinkText: string;
		quoteText: string;
	}

	const APP_REGISTRY: Record<string, EmbedSection[]> = {
		code: [
			{
				skillLabel: 'Code',
				appId: 'code',
				previewPath: 'embeds/code/CodeEmbedPreview',
				fullscreenPath: 'embeds/code/CodeEmbedFullscreen',
				inlineLinkText: 'MyComponent.svelte',
				quoteText: 'let count = $state(0); — Svelte 5 reactive state declaration'
			},
			{
				skillLabel: 'Get Docs',
				appId: 'code',
				previewPath: 'embeds/code/CodeGetDocsEmbedPreview',
				fullscreenPath: 'embeds/code/CodeGetDocsEmbedFullscreen',
				inlineLinkText: 'Svelte $state documentation',
				quoteText: 'The $state rune declares reactive state that updates the UI automatically.'
			}
		],
		docs: [
			{
				skillLabel: 'Document',
				appId: 'docs',
				previewPath: 'embeds/docs/DocsEmbedPreview',
				fullscreenPath: 'embeds/docs/DocsEmbedFullscreen',
				inlineLinkText: 'architecture.docx',
				quoteText: 'PostgreSQL serves as the primary data store, managed through Directus CMS.'
			}
		],
		web: [
			{
				skillLabel: 'Search',
				appId: 'web',
				previewPath: 'embeds/web/WebSearchEmbedPreview',
				fullscreenPath: 'embeds/web/WebSearchEmbedFullscreen',
				inlineLinkText: 'Best restaurants in Berlin',
				quoteText: 'Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.'
			},
			{
				skillLabel: 'Read',
				appId: 'web',
				previewPath: 'embeds/web/WebReadEmbedPreview',
				fullscreenPath: 'embeds/web/WebReadEmbedFullscreen',
				inlineLinkText: 'Migrating from Svelte 4 to 5',
				quoteText: 'Svelte 5 introduces runes, a powerful new reactivity system that replaces $: reactive statements.'
			},
			{
				skillLabel: 'Website',
				appId: 'web',
				previewPath: 'embeds/web/WebsiteEmbedPreview',
				fullscreenPath: 'embeds/web/WebsiteEmbedFullscreen',
				inlineLinkText: 'svelte.dev',
				quoteText: 'Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM.'
			}
		],
		videos: [
			{
				skillLabel: 'Video',
				appId: 'videos',
				previewPath: 'embeds/videos/VideoEmbedPreview',
				fullscreenPath: 'embeds/videos/VideoEmbedFullscreen',
				inlineLinkText: 'Understanding Svelte 5 Runes',
				quoteText: 'Runes are a powerful new reactivity system that simplifies state management.'
			},
			{
				skillLabel: 'Transcript',
				appId: 'videos',
				previewPath: 'embeds/videos/VideoTranscriptEmbedPreview',
				fullscreenPath: 'embeds/videos/VideoTranscriptEmbedFullscreen',
				inlineLinkText: 'Svelte 5 Runes transcript',
				quoteText: 'Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system.'
			},
			{
				skillLabel: 'Search',
				appId: 'videos',
				previewPath: 'embeds/videos/VideosSearchEmbedPreview',
				fullscreenPath: 'embeds/videos/VideosSearchEmbedFullscreen',
				inlineLinkText: 'Svelte 5 tutorial search',
				quoteText: 'Found 24 results for "svelte 5 tutorial" — curated from YouTube.'
			}
		],
		images: [
			{
				skillLabel: 'Generate',
				appId: 'images',
				previewPath: 'embeds/images/ImageGenerateEmbedPreview',
				fullscreenPath: 'embeds/images/ImageGenerateEmbedFullscreen',
				inlineLinkText: 'Cat wearing a top hat',
				quoteText: 'Generated image: a quick sketch of a cat wearing a top hat, pencil style.'
			}
		],
		news: [
			{
				skillLabel: 'Article',
				appId: 'news',
				previewPath: 'embeds/news/NewsEmbedPreview',
				fullscreenPath: 'embeds/news/NewsEmbedFullscreen',
				inlineLinkText: 'Svelte 5 officially released',
				quoteText: 'The latest version of the popular frontend framework brings fundamental changes to reactivity.'
			},
			{
				skillLabel: 'Search',
				appId: 'news',
				previewPath: 'embeds/news/NewsSearchEmbedPreview',
				fullscreenPath: 'embeds/news/NewsSearchEmbedFullscreen',
				inlineLinkText: 'Latest technology news 2026',
				quoteText: 'New AI-powered development tools are changing how developers write, test, and deploy software.'
			}
		],
		travel: [
			{
				skillLabel: 'Search',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelSearchEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelSearchEmbedFullscreen',
				inlineLinkText: 'Munich → London, Mar 15',
				quoteText: 'Lufthansa LH2485: Munich → London Heathrow, 2h 10m, from €89.'
			},
			{
				skillLabel: 'Connection',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelConnectionEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelConnectionEmbedFullscreen',
				inlineLinkText: 'MUC → LHR direct flight',
				quoteText: 'Direct flight Munich to London, 2h 10min, Terminal 2, Gate B22.'
			},
			{
				skillLabel: 'Price Calendar',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelPriceCalendarEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelPriceCalendarEmbedFullscreen',
				inlineLinkText: 'Munich → Barcelona prices, March',
				quoteText: 'Cheapest day: March 18 at €62. Prices shown for Munich → Barcelona.'
			},
			{
				skillLabel: 'Stay',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelStayEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelStayEmbedFullscreen',
				inlineLinkText: 'Hotel Maximilian, Munich',
				quoteText: 'Hotel Maximilian: 4-star hotel in central Munich, from €387 for 3 nights.'
			},
			{
				skillLabel: 'Stays Search',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelStaysEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelStaysEmbedFullscreen',
				inlineLinkText: 'Hotels in Barcelona, Mar 15-18',
				quoteText: 'Found 8 hotels in Barcelona for Mar 15-18. Top pick: Hotel Arts Barcelona.'
			}
		],
		maps: [
			{
				skillLabel: 'Search',
				appId: 'maps',
				previewPath: 'embeds/maps/MapsSearchEmbedPreview',
				fullscreenPath: 'embeds/maps/MapsSearchEmbedFullscreen',
				inlineLinkText: 'Coffee shops near Marienplatz',
				quoteText: 'Man vs. Machine Coffee Roasters — Rated 4.7, 0.3km from Marienplatz, Munich.'
			}
		],
		math: [
			{
				skillLabel: 'Calculate',
				appId: 'math',
				previewPath: 'embeds/math/MathCalculateEmbedPreview',
				fullscreenPath: 'embeds/math/MathCalculateEmbedFullscreen',
				inlineLinkText: 'sin(π/4) + cos(π/3)',
				quoteText: 'Result: sin(π/4) + cos(π/3) = √2/2 + 1/2 ≈ 1.207'
			},
			{
				skillLabel: 'Plot',
				appId: 'math',
				previewPath: 'embeds/math/MathPlotEmbedPreview',
				fullscreenPath: 'embeds/math/MathPlotEmbedFullscreen',
				inlineLinkText: 'sin(x) and cos(x) plot',
				quoteText: 'Interactive plot of f(x) = sin(x) and f(x) = cos(x) over [−2π, 2π].'
			}
		],
		events: [
			{
				skillLabel: 'Event',
				appId: 'events',
				previewPath: 'embeds/events/EventEmbedPreview',
				fullscreenPath: 'embeds/events/EventEmbedFullscreen',
				inlineLinkText: 'AI & ML Berlin Meetup',
				quoteText: 'AI & Machine Learning Berlin Meetup – Spring Edition. March 15, 19:00 at Factory Berlin.'
			},
			{
				skillLabel: 'Search',
				appId: 'events',
				previewPath: 'embeds/events/EventsSearchEmbedPreview',
				fullscreenPath: 'embeds/events/EventsSearchEmbedFullscreen',
				inlineLinkText: 'AI meetups in Berlin',
				quoteText: 'Found 3 upcoming AI & tech events in Berlin this month.'
			}
		],
		reminder: [
			{
				skillLabel: 'Reminder',
				appId: 'reminder',
				previewPath: 'embeds/reminder/ReminderEmbedPreview',
				fullscreenPath: 'embeds/reminder/ReminderEmbedFullscreen',
				inlineLinkText: 'Reminder: tomorrow 9:00 AM',
				quoteText: 'Reminder set! I will send a message in this chat tomorrow at 9:00 AM.'
			}
		],
		sheets: [
			{
				skillLabel: 'Sheet',
				appId: 'sheets',
				previewPath: 'embeds/sheets/SheetEmbedPreview',
				fullscreenPath: 'embeds/sheets/SheetEmbedFullscreen',
				inlineLinkText: 'Budget spreadsheet Q1 2026',
				quoteText: 'Spreadsheet: Q1 2026 Budget — 12 rows, 8 columns, last updated today.'
			}
		],
		audio: [
			{
				skillLabel: 'Recording',
				appId: 'audio',
				previewPath: 'embeds/audio/RecordingEmbedPreview',
				fullscreenPath: 'embeds/audio/RecordingEmbedFullscreen',
				inlineLinkText: 'Voice note — 0:42',
				quoteText: 'Voice recording captured: 42 seconds, transcription available.'
			}
		],
		health: [
			{
				skillLabel: 'Appointment',
				appId: 'health',
				previewPath: 'embeds/health/HealthAppointmentEmbedPreview',
				fullscreenPath: 'embeds/health/HealthAppointmentEmbedFullscreen',
				inlineLinkText: 'Dr. Müller appointment — Apr 3',
				quoteText: 'Appointment confirmed with Dr. Müller on April 3 at 10:30 AM.'
			},
			{
				skillLabel: 'Search',
				appId: 'health',
				previewPath: 'embeds/health/HealthSearchEmbedPreview',
				fullscreenPath: 'embeds/health/HealthSearchEmbedFullscreen',
				inlineLinkText: 'Cardiologists near Munich',
				quoteText: 'Found 5 cardiologists within 5km. Top result: Prof. Weber, rated 4.9.'
			}
		],
		mail: [
			{
				skillLabel: 'Mail',
				appId: 'mail',
				previewPath: 'embeds/mail/MailEmbedPreview',
				fullscreenPath: 'embeds/mail/MailEmbedFullscreen',
				inlineLinkText: 'Email: Project update from Anna',
				quoteText: 'The latest sprint review went well. All tickets closed except the auth refactor.'
			}
		],
		pdf: [
			{
				skillLabel: 'PDF',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PDFEmbedPreview',
				fullscreenPath: 'embeds/pdf/PDFEmbedFullscreen',
				inlineLinkText: 'Q4 2025 Report.pdf',
				quoteText: 'Annual revenue increased 23% YoY. Full analysis on pages 4–7.'
			},
			{
				skillLabel: 'Read',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PdfReadEmbedPreview',
				fullscreenPath: 'embeds/pdf/PdfReadEmbedFullscreen',
				inlineLinkText: 'Architecture whitepaper — page 12',
				quoteText: 'The microservices architecture enables independent scaling of each service component.'
			},
			{
				skillLabel: 'Search',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PdfSearchEmbedPreview',
				fullscreenPath: 'embeds/pdf/PdfSearchEmbedFullscreen',
				inlineLinkText: 'Search "authentication" in docs',
				quoteText: 'Found 7 mentions of "authentication" across 3 documents.'
			}
		],
		shopping: [
			{
				skillLabel: 'Search',
				appId: 'shopping',
				previewPath: 'embeds/shopping/ShoppingSearchEmbedPreview',
				fullscreenPath: 'embeds/shopping/ShoppingSearchEmbedFullscreen',
				inlineLinkText: 'Wireless headphones under €100',
				quoteText: 'Found 12 wireless headphones under €100. Top pick: Sony WH-1000XM4 at €89.'
			}
		]
	};

	const ALL_APPS = [
		'code', 'docs', 'web', 'videos', 'images', 'news', 'travel',
		'maps', 'math', 'events', 'reminder', 'sheets', 'audio',
		'health', 'mail', 'pdf', 'shopping'
	];

	// ─── Glob maps ────────────────────────────────────────────────────────────
	const componentModules = import.meta.glob<{ default: unknown }>(
		'/../../packages/ui/src/components/**/*.svelte',
		{ eager: false }
	);
	const previewModules = import.meta.glob<{
		default: Record<string, unknown>;
		variants?: Record<string, Record<string, unknown>>;
	}>('/../../packages/ui/src/components/**/*.preview.ts', { eager: false });

	function extractCleanPath(fullPath: string): string {
		const marker = '/components/';
		const idx = fullPath.indexOf(marker);
		if (idx !== -1) return fullPath.substring(idx + marker.length);
		const BASE = '/../../packages/ui/src/components/';
		if (fullPath.startsWith(BASE)) return fullPath.substring(BASE.length);
		return fullPath;
	}

	const componentKeyMap = new Map<string, string>();
	for (const key of Object.keys(componentModules)) {
		componentKeyMap.set(extractCleanPath(key).replace('.svelte', ''), key);
	}
	const previewKeyMap = new Map<string, string>();
	for (const key of Object.keys(previewModules)) {
		previewKeyMap.set(extractCleanPath(key).replace('.preview.ts', ''), key);
	}

	// ─── Route state ──────────────────────────────────────────────────────────
	let currentApp = $derived(page.params.app || 'code');
	let sections = $derived(APP_REGISTRY[currentApp] ?? []);
	let isUnknownApp = $derived(!(currentApp in APP_REGISTRY));

	// ─── Global toolbar ───────────────────────────────────────────────────────
	let background = $state<'auto' | 'grid'>('auto');
	let backgroundStyle = $derived.by(() => {
		if (background === 'grid') {
			return `background-color: var(--color-grey-0);
				background-image: linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%),
				linear-gradient(-45deg, var(--color-grey-20) 25%, transparent 25%),
				linear-gradient(45deg, transparent 75%, var(--color-grey-20) 75%),
				linear-gradient(-45deg, transparent 75%, var(--color-grey-20) 75%);
				background-size: 20px 20px;
				background-position: 0 0, 0 10px, 10px -10px, -10px 0px;`;
		}
		return 'background: var(--color-grey-0);';
	});

	function toggleTheme() {
		theme.set($theme === 'light' ? 'dark' : 'light');
	}

	// ─── Per-section state ────────────────────────────────────────────────────
	interface SectionState {
		previewComponent: unknown;
		fullscreenComponent: unknown;
		loadError: string | null;
		isLoading: boolean;
		mockProps: Record<string, unknown>;
		variants: Record<string, Record<string, unknown>>;
		hasPreviewFile: boolean;
		activeVariant: string;
		manualOverrides: Record<string, unknown>;
		hasManualEdits: boolean;
		propsJson: string;
		propsError: string | null;
		showPropsEditor: boolean;
		mobileError: string | null;
		smallError: string | null;
		largeError: string | null;
		fsError: string | null;
	}

	let sectionStates = $state<SectionState[]>([]);

	$effect(() => {
		const snap = sections;
		sectionStates = snap.map(() => ({
			previewComponent: null,
			fullscreenComponent: null,
			loadError: null,
			isLoading: true,
			mockProps: {},
			variants: {},
			hasPreviewFile: false,
			activeVariant: 'default',
			manualOverrides: {},
			hasManualEdits: false,
			propsJson: '{}',
			propsError: null,
			showPropsEditor: false,
			mobileError: null,
			smallError: null,
			largeError: null,
			fsError: null
		}));
		snap.forEach((section, i) => loadSection(section, i));
	});

	async function loadSection(section: EmbedSection, idx: number) {
		const s = sectionStates[idx];
		if (!s) return;
		s.isLoading = true;
		s.loadError = null;

		const prevKey = previewKeyMap.get(section.previewPath) ?? '';
		const previewKey = componentKeyMap.get(section.previewPath) ?? '';
		const fullscreenKey = componentKeyMap.get(section.fullscreenPath) ?? '';

		try {
			if (!previewKey) throw new Error(`Component not found: ${section.previewPath}.svelte`);
			const [previewMod, fullscreenMod] = await Promise.all([
				componentModules[previewKey](),
				fullscreenKey ? componentModules[fullscreenKey]() : Promise.resolve(null)
			]);
			s.previewComponent = previewMod?.default ?? null;
			s.fullscreenComponent = (fullscreenMod as { default?: unknown } | null)?.default ?? null;

			if (prevKey && previewModules[prevKey]) {
				try {
					const preview = await previewModules[prevKey]();
					s.mockProps = preview.default ?? {};
					s.variants = preview.variants ?? {};
					s.hasPreviewFile = true;
					s.propsJson = JSON.stringify(preview.default ?? {}, null, 2);
				} catch { /* no preview file */ }
			}
		} catch (err) {
			s.loadError = err instanceof Error ? err.message : String(err);
		} finally {
			s.isLoading = false;
		}
	}

	function getEffectiveProps(s: SectionState): Record<string, unknown> {
		const base = { ...s.mockProps };
		if (s.activeVariant !== 'default' && s.variants[s.activeVariant]) {
			Object.assign(base, s.variants[s.activeVariant]);
		}
		if (s.hasManualEdits) Object.assign(base, s.manualOverrides);
		return base;
	}

	function selectVariant(idx: number, name: string) {
		const s = sectionStates[idx];
		if (!s) return;
		s.activeVariant = name;
		s.hasManualEdits = false;
		s.manualOverrides = {};
		s.propsError = null;
		s.propsJson = JSON.stringify(getEffectiveProps(s), null, 2);
		s.mobileError = null;
		s.smallError = null;
		s.largeError = null;
		s.fsError = null;
	}

	function handlePropsInput(idx: number, value: string) {
		const s = sectionStates[idx];
		if (!s) return;
		s.propsJson = value;
		s.hasManualEdits = true;
		try {
			const parsed = JSON.parse(value);
			if (typeof parsed === 'object' && parsed !== null) {
				s.manualOverrides = parsed;
				s.propsError = null;
			}
		} catch (err) {
			s.propsError = err instanceof Error ? err.message : 'Invalid JSON';
		}
	}

	function resetProps(idx: number) {
		const s = sectionStates[idx];
		if (!s) return;
		s.manualOverrides = {};
		s.hasManualEdits = false;
		s.propsError = null;
		s.propsJson = JSON.stringify(getEffectiveProps(s), null, 2);
	}

	// ─── Component mounting ───────────────────────────────────────────────────
	// 4 mount targets per section: 0=mobile, 1=small, 2=large, 3=fullscreen
	let mountTargets = $state<(HTMLElement | null)[]>([]);
	const mountedInstances = new Map<number, ReturnType<typeof mount>>();

	function key(sIdx: number, dIdx: number) { return sIdx * 4 + dIdx; }

	function cleanupMount(k: number) {
		const inst = mountedInstances.get(k);
		if (inst) {
			try { unmount(inst); } catch { /* ignore */ }
			mountedInstances.delete(k);
		}
		const el = mountTargets[k];
		if (el) el.innerHTML = '';
	}

	function mountComp(
		k: number,
		component: unknown,
		target: HTMLElement | null,
		props: Record<string, unknown>,
		onErr: (m: string) => void
	) {
		if (!component || !target) return;
		cleanupMount(k);
		let caught = false;
		const onError = (e: ErrorEvent) => {
			if (!caught) {
				caught = true;
				onErr(e.error?.message ?? e.message ?? 'Unknown render error');
				cleanupMount(k);
			}
			e.preventDefault();
		};
		window.addEventListener('error', onError);
		try {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			mountedInstances.set(k, mount(component as any, { target, props }));
		} catch (err) {
			caught = true;
			onErr(err instanceof Error ? err.message : String(err));
			cleanupMount(k);
		}
		const t = setTimeout(() => window.removeEventListener('error', onError), 500);
		return () => { clearTimeout(t); window.removeEventListener('error', onError); };
	}

	$effect(() => {
		sectionStates.forEach((s, si) => {
			if (s.isLoading || s.loadError) return;
			const props = getEffectiveProps(s);

			if (!s.mobileError) {
				mountComp(key(si, 0), s.previewComponent, mountTargets[key(si, 0)],
					{ ...props, isMobile: true }, (m) => { sectionStates[si].mobileError = m; });
			}
			if (!s.smallError) {
				mountComp(key(si, 1), s.previewComponent, mountTargets[key(si, 1)],
					{ ...props, isMobile: false }, (m) => { sectionStates[si].smallError = m; });
			}
			if (!s.largeError) {
				mountComp(key(si, 2), s.previewComponent, mountTargets[key(si, 2)],
					{ ...props, isMobile: false }, (m) => { sectionStates[si].largeError = m; });
			}
			if (!s.fsError) {
				mountComp(key(si, 3), s.fullscreenComponent, mountTargets[key(si, 3)],
					{ ...props, onClose: () => {} }, (m) => { sectionStates[si].fsError = m; });
			}
		});
		return () => { for (const [k] of mountedInstances) cleanupMount(k); };
	});

	function retrySection(si: number) {
		const s = sectionStates[si];
		if (!s) return;
		s.mobileError = null;
		s.smallError = null;
		s.largeError = null;
		s.fsError = null;
	}
</script>

<div class="showcase-page">

	<!-- ── App switcher bar ───────────────────────────────────────────── -->
	<header class="app-switcher">
		<a href="/dev/preview" class="back-link">← All</a>
		<nav class="app-pills" aria-label="Switch embed app">
			{#each ALL_APPS as appSlug}
				<a
					class="app-pill"
					class:active={appSlug === currentApp}
					href="/dev/preview/embeds/{appSlug}"
				>{appSlug}</a>
			{/each}
		</nav>
		<div class="toolbar-right">
			<button class="theme-btn" onclick={toggleTheme} title="Toggle theme">
				{$theme === 'light' ? '🌙' : '☀️'}
			</button>
			<div class="bg-group">
				<button class="ctrl-btn" class:active={background === 'auto'} onclick={() => (background = 'auto')}>Auto</button>
				<button class="ctrl-btn" class:active={background === 'grid'} onclick={() => (background = 'grid')}>Grid</button>
			</div>
		</div>
	</header>

	<!-- ── Scrollable content ─────────────────────────────────────────── -->
	<div class="showcase-body" style={backgroundStyle}>
		{#if isUnknownApp}
			<div class="unknown-app">
				<h2>Unknown app: "{currentApp}"</h2>
				<p>Available: {ALL_APPS.join(', ')}</p>
			</div>
		{:else}
			<div class="app-heading">
				<h1 class="app-title">{currentApp}</h1>
				<span class="section-count">{sections.length} skill{sections.length !== 1 ? 's' : ''}</span>
			</div>

			{#each sections as section, si}
				{@const s = sectionStates[si]}

				<section class="skill-section">

					<!-- Section header -->
					<div class="skill-header">
						<h2 class="skill-label">{section.skillLabel}</h2>
						{#if s}
							<div class="skill-actions">
								{#if Object.keys(s.variants).length > 0}
									<div class="template-row">
										<span class="template-label">Template:</span>
										<button
											class="tmpl-btn"
											class:active={s.activeVariant === 'default'}
											onclick={() => selectVariant(si, 'default')}
										>Default</button>
										{#each Object.keys(s.variants) as vname}
											<button
												class="tmpl-btn"
												class:active={s.activeVariant === vname}
												onclick={() => selectVariant(si, vname)}
											>{vname}</button>
										{/each}
									</div>
								{/if}
								<button
									class="props-btn"
									class:active={s.showPropsEditor}
									onclick={() => { sectionStates[si].showPropsEditor = !sectionStates[si].showPropsEditor; }}
								>Props</button>
							</div>
						{/if}
					</div>

					{#if s?.isLoading}
						<p class="section-loading">Loading {section.skillLabel}…</p>
					{:else if s?.loadError}
						<p class="section-error">{s.loadError}</p>
					{:else if s}

						<!-- Props panel -->
						{#if s.showPropsEditor}
							<div class="props-panel">
								<div class="props-panel-hdr">
									<span class="props-panel-title">Props JSON</span>
									{#if s.hasManualEdits}
										<button class="reset-btn" onclick={() => resetProps(si)}>Reset</button>
									{/if}
									{#if !s.hasPreviewFile}
										<span class="no-preview">No .preview.ts</span>
									{/if}
								</div>
								<textarea
									class="props-editor"
									value={s.propsJson}
									oninput={(e) => handlePropsInput(si, (e.target as HTMLTextAreaElement).value)}
									spellcheck="false"
								></textarea>
								{#if s.propsError}
									<p class="props-error">{s.propsError}</p>
								{/if}
							</div>
						{/if}

						<!-- 1. Inline Link -->
						<div class="dt">
							<h3 class="dt-heading">Inline Link</h3>
							<div class="dt-body dt-body--inline">
								<span class="inline-ctx">The assistant found </span>
								<span class="fake-inline">
									<span class="fake-badge" style="background: var(--color-app-{section.appId})"></span>
									<span class="fake-link-text">{section.inlineLinkText}</span>
								</span>
								<span class="inline-ctx"> for you.</span>
							</div>
						</div>

						<!-- 2. Quote Block -->
						<div class="dt">
							<h3 class="dt-heading">Quote Block</h3>
							<div class="dt-body">
								<blockquote
									class="fake-quote"
									style="border-left-color: var(--color-app-{section.appId}-start, var(--color-primary-start))"
								>
									<p class="fake-quote-text">{section.quoteText}</p>
									<footer class="fake-quote-footer">
										<span class="fake-badge fake-badge--sm" style="background: var(--color-app-{section.appId})"></span>
										<span class="fake-source">{section.appId}</span>
									</footer>
								</blockquote>
							</div>
						</div>

						<!-- 3. Preview — Mobile -->
						<div class="dt">
							<h3 class="dt-heading">Preview — Mobile <span class="size-hint">150×290</span></h3>
							<div class="dt-body">
								{#if s.mobileError}
									<div class="render-err">
										<strong>Render error</strong>
										<code>{s.mobileError}</code>
										<button onclick={() => retrySection(si)}>Retry</button>
									</div>
								{/if}
								<div
									class="mount-target"
									style:display={s.mobileError ? 'none' : 'block'}
									bind:this={mountTargets[key(si, 0)]}
								></div>
							</div>
						</div>

						<!-- 4. Preview — Small -->
						<div class="dt">
							<h3 class="dt-heading">Preview — Small <span class="size-hint">300×200</span></h3>
							<div class="dt-body">
								{#if s.smallError}
									<div class="render-err">
										<strong>Render error</strong>
										<code>{s.smallError}</code>
										<button onclick={() => retrySection(si)}>Retry</button>
									</div>
								{/if}
								<div
									class="mount-target"
									style:display={s.smallError ? 'none' : 'block'}
									bind:this={mountTargets[key(si, 1)]}
								></div>
							</div>
						</div>

						<!-- 5. Preview — Large -->
						<!-- The wrapper sets container-type:inline-size + container-name:embed-preview
						     which triggers @container embed-preview (min-width: 301px) in
						     UnifiedEmbedPreview, switching to the full-width × 400px layout. -->
						<div class="dt">
							<h3 class="dt-heading">Preview — Large <span class="size-hint">full-width × 400</span></h3>
							<div class="dt-body dt-body--flush">
								<div class="large-container">
									{#if s.largeError}
										<div class="render-err">
											<strong>Render error</strong>
											<code>{s.largeError}</code>
											<button onclick={() => retrySection(si)}>Retry</button>
										</div>
									{/if}
									<div
										class="mount-target"
										style:display={s.largeError ? 'none' : 'block'}
										bind:this={mountTargets[key(si, 2)]}
									></div>
								</div>
							</div>
						</div>

						<!-- 6. Fullscreen -->
						<!-- isolation:isolate + overflow:hidden clips position:fixed children
						     so the fullscreen component renders inline without covering the page. -->
						<div class="dt">
							<h3 class="dt-heading">Fullscreen <span class="size-hint">clipped inline</span></h3>
							<div class="dt-body dt-body--flush">
								<div class="fs-clip">
									{#if s.fsError}
										<div class="render-err">
											<strong>Render error</strong>
											<code>{s.fsError}</code>
											<button onclick={() => retrySection(si)}>Retry</button>
										</div>
									{/if}
									<div
										class="mount-target mount-target--fs"
										style:display={s.fsError ? 'none' : 'block'}
										bind:this={mountTargets[key(si, 3)]}
									></div>
								</div>
							</div>
						</div>

					{/if}
				</section>
			{/each}
		{/if}
	</div>
</div>

<style>
	/* ── Page shell ──────────────────────────────────────────────────── */
	.showcase-page {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary);
	}

	/* ── App switcher ────────────────────────────────────────────────── */
	.app-switcher {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 8px 16px;
		background: var(--color-grey-10);
		border-bottom: 1px solid var(--color-grey-25);
		flex-shrink: 0;
		overflow: hidden;
	}

	.back-link {
		font-size: 0.8125rem;
		color: var(--color-primary-start);
		text-decoration: none;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.back-link:hover { text-decoration: underline; }

	.app-pills {
		display: flex;
		gap: 6px;
		overflow-x: auto;
		flex: 1;
		scrollbar-width: none;
		-ms-overflow-style: none;
		padding-bottom: 2px;
		min-width: 0;
	}
	.app-pills::-webkit-scrollbar { display: none; }

	.app-pill {
		padding: 4px 12px;
		border-radius: 20px;
		font-size: 0.8125rem;
		font-weight: 500;
		text-decoration: none;
		white-space: nowrap;
		flex-shrink: 0;
		color: var(--color-font-secondary);
		background: var(--color-grey-20);
		border: 1px solid transparent;
		transition: background-color 0.15s, color 0.15s;
	}
	.app-pill:hover { background: var(--color-grey-25); color: var(--color-font-primary); }
	.app-pill.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional: always white text on gradient active pill */
		border-color: var(--color-primary-start);
	}

	.toolbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.theme-btn {
		padding: 4px 8px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-10);
		cursor: pointer;
		font-size: 0.875rem;
		line-height: 1;
	}

	.bg-group {
		display: flex;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		overflow: hidden;
	}
	.ctrl-btn {
		padding: 4px 10px;
		border: none;
		border-right: 1px solid var(--color-grey-30);
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		transition: background-color 0.15s;
	}
	.ctrl-btn:last-child { border-right: none; }
	.ctrl-btn:hover { background: var(--color-grey-20); }
	.ctrl-btn.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional: always white on active toggle */
	}

	/* ── Scrollable body ─────────────────────────────────────────────── */
	.showcase-body {
		flex: 1;
		overflow-y: auto;
		padding: 32px 40px 80px;
	}

	.app-heading {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 40px;
	}
	.app-title {
		font-size: 1.75rem;
		font-weight: 700;
		margin: 0;
		text-transform: capitalize;
	}
	.section-count {
		font-size: 0.875rem;
		color: var(--color-font-tertiary);
	}

	/* ── Skill section ───────────────────────────────────────────────── */
	.skill-section {
		margin-bottom: 64px;
		padding-bottom: 48px;
		border-bottom: 1px solid var(--color-grey-25);
	}
	.skill-section:last-child { border-bottom: none; margin-bottom: 0; }

	.skill-header {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		margin-bottom: 28px;
	}
	.skill-label {
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0;
	}
	.skill-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-left: auto;
	}

	.template-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.template-label {
		font-size: 0.75rem;
		color: var(--color-font-tertiary);
		white-space: nowrap;
	}
	.tmpl-btn {
		padding: 3px 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		white-space: nowrap;
		transition: background-color 0.15s;
	}
	.tmpl-btn:hover:not(.active) { background: var(--color-grey-20); }
	.tmpl-btn.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional: always white on active template pill */
		border-color: var(--color-primary-start);
	}

	.props-btn {
		padding: 3px 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-tertiary);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		transition: background-color 0.15s;
	}
	.props-btn:hover { background: var(--color-grey-20); color: var(--color-font-primary); }
	.props-btn.active { background: var(--color-grey-25); color: var(--color-font-primary); border-color: var(--color-grey-30); }

	/* ── Props panel ─────────────────────────────────────────────────── */
	.props-panel {
		margin-bottom: 24px;
		padding: 16px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-grey-25);
		border-radius: 10px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.props-panel-hdr {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.props-panel-title { font-size: 0.8125rem; font-weight: 600; }
	.reset-btn {
		padding: 2px 8px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-tertiary);
		font-size: 0.6875rem;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}
	.reset-btn:hover { background: var(--color-grey-20); color: var(--color-font-primary); }
	.no-preview {
		margin-left: auto;
		font-size: 0.6875rem;
		color: var(--color-font-tertiary);
		font-style: italic;
	}
	.props-editor {
		width: 100%;
		min-height: 160px;
		padding: 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-0);
		color: var(--color-font-primary);
		font-family: 'Courier New', monospace;
		font-size: 0.75rem;
		line-height: 1.5;
		resize: vertical;
		outline: none;
		box-sizing: border-box;
	}
	.props-editor:focus { border-color: var(--color-primary-start); }
	.props-error { font-size: 0.6875rem; color: var(--color-error, #e53935); margin: 0; }

	/* ── Display type rows ───────────────────────────────────────────── */
	.dt { margin-bottom: 36px; }

	.dt-heading {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-font-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		margin: 0 0 10px;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.size-hint {
		font-size: 0.6875rem;
		font-weight: 400;
		color: var(--color-font-tertiary);
		text-transform: none;
		letter-spacing: 0;
		font-family: 'Courier New', monospace;
		opacity: 0.8;
	}

	.dt-body {
		padding: 20px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-grey-25);
		border-radius: 12px;
		min-height: 40px;
	}

	/* Inline: flow-text context */
	.dt-body--inline {
		font-size: 0.9375rem;
		line-height: 1.6;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 3px;
	}
	.inline-ctx { color: var(--color-font-primary); }

	/* Fake EmbedInlineLink */
	.fake-inline {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.fake-badge {
		display: inline-flex;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.fake-badge--sm { width: 18px; height: 18px; }
	.fake-link-text {
		font-size: 0.9375rem;
		font-weight: 500;
		color: var(--color-primary-start);
	}

	/* Fake SourceQuoteBlock */
	.fake-quote {
		margin: 0;
		padding: 10px 16px;
		border-left: 3px solid var(--color-primary-start);
		background: var(--color-grey-0);
		border-radius: 0 8px 8px 0;
	}
	.fake-quote-text {
		font-style: italic;
		font-size: 0.9375rem;
		line-height: 1.6;
		color: var(--color-font-primary);
		margin: 0 0 8px;
	}
	.fake-quote-footer {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.fake-source { font-size: 0.75rem; color: var(--color-font-tertiary); }

	/* Large preview — establishes the container query context.
	   container-name: embed-preview triggers
	   @container embed-preview (min-width: 301px) in UnifiedEmbedPreview,
	   switching to the full-width × 400px expanded layout. */
	.dt-body--flush {
		padding: 0;
		background: transparent;
		border: none;
	}
	.large-container {
		container-type: inline-size;
		container-name: embed-preview;
		width: 100%;
		min-width: 320px;
		border-radius: 12px;
		overflow: hidden;
		border: 1px solid var(--color-grey-25);
	}

	/* Fullscreen clip — isolation:isolate creates a stacking context so that
	   the fullscreen component's position:fixed children are clipped to this box
	   instead of escaping to the viewport. */
	.fs-clip {
		position: relative;
		width: 100%;
		height: 560px;
		overflow: hidden;
		isolation: isolate;
		border-radius: 12px;
		border: 1px solid var(--color-grey-25);
	}

	/* ── Mount targets ───────────────────────────────────────────────── */
	.mount-target { min-height: 20px; }
	.mount-target--fs {
		position: absolute;
		inset: 0;
	}

	/* ── Render errors ───────────────────────────────────────────────── */
	.render-err {
		padding: 12px 16px;
		background: var(--color-grey-10);
		border: 1px solid color-mix(in srgb, var(--color-error, #e53935) 30%, transparent);
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 0.8125rem;
		margin-bottom: 8px;
	}
	.render-err strong { color: var(--color-error, #e53935); }
	.render-err code {
		font-family: 'Courier New', monospace;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		word-break: break-word;
	}
	.render-err button {
		align-self: flex-start;
		padding: 4px 12px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}
	.render-err button:hover { background: var(--color-grey-20); }

	/* ── State messages ──────────────────────────────────────────────── */
	.section-loading { padding: 24px 0; color: var(--color-font-tertiary); font-size: 0.875rem; }
	.section-error {
		padding: 16px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-error, #e53935);
		border-radius: 8px;
		color: var(--color-error, #e53935);
		font-size: 0.875rem;
		font-family: 'Courier New', monospace;
	}

	.unknown-app { padding: 48px 0; text-align: center; color: var(--color-font-tertiary); }
	.unknown-app h2 { font-size: 1.25rem; margin: 0 0 8px; }
	.unknown-app p { font-size: 0.875rem; margin: 0; }
</style>
