<!--
  Embed App Showcase Page.
  Shows ALL embed display types for a given app on a single scrollable page.

  URL: /dev/preview/embeds/<app>
  Examples:
    /dev/preview/embeds/code
    /dev/preview/embeds/web
    /dev/preview/embeds/travel

  Display types shown per skill section:
    1. Inline Link         (simulated visual replica)
    2. Quote Block         (simulated visual replica)
    3. Group — Small       (horizontal scroll row of all data variants, isMobile=false → 300x200px)
    4. Group — Large       (slideshow carousel of all data variants with prev/next) — hidden for app skills
    5. Fullscreen          (clipped inline, cycles through variants with prev/next)

  "Preview — Large" was removed (Group — Large already covers that use case).
  "Group — Large" is also hidden for app-skill embeds, since app skills are never
  promoted to a large single-embed carousel in production.

  "Data variants" = all named variants except 'error'/'mobile'/'processing' + the default.

  Architecture: uses Svelte 5 native dynamic component rendering (<Component />)
  instead of imperative mount()/unmount(). Each loaded component is stored as a
  class ref in $state and rendered declaratively — Svelte handles the lifecycle.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { Icon, theme } from '@repo/ui';

	// ─── App Registry ─────────────────────────────────────────────────

	interface EmbedSection {
		skillLabel: string;
		appId: string;
		previewPath: string;
		fullscreenPath: string;
		inlineLinkText: string;
		quoteText: string;
		/** True for app-skill-use embeds (AppSkillUseRenderer). Group — Large is hidden for these. */
		isAppSkill?: boolean;
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
				quoteText: 'The $state rune declares reactive state that updates the UI automatically.',
				isAppSkill: true
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
				quoteText:
					'Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.',
				isAppSkill: true
			},
			{
				skillLabel: 'Read',
				appId: 'web',
				previewPath: 'embeds/web/WebReadEmbedPreview',
				fullscreenPath: 'embeds/web/WebReadEmbedFullscreen',
				inlineLinkText: 'Migrating from Svelte 4 to 5',
				quoteText:
					'Svelte 5 introduces runes, a powerful new reactivity system that replaces $: reactive statements.',
				isAppSkill: true
			},
			{
				skillLabel: 'Website',
				appId: 'web',
				previewPath: 'embeds/web/WebsiteEmbedPreview',
				fullscreenPath: 'embeds/web/WebsiteEmbedFullscreen',
				inlineLinkText: 'svelte.dev',
				quoteText:
					'Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM.'
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
				quoteText: 'Today we are going to learn about Svelte 5 runes.',
				isAppSkill: true
			},
			{
				skillLabel: 'Search',
				appId: 'videos',
				previewPath: 'embeds/videos/VideosSearchEmbedPreview',
				fullscreenPath: 'embeds/videos/VideosSearchEmbedFullscreen',
				inlineLinkText: 'Svelte 5 tutorial search',
				quoteText: 'Found 24 results for "svelte 5 tutorial" — curated from YouTube.',
				isAppSkill: true
			}
		],
		images: [
			{
				skillLabel: 'Generate',
				appId: 'images',
				previewPath: 'embeds/images/ImageGenerateEmbedPreview',
				fullscreenPath: 'embeds/images/ImageGenerateEmbedFullscreen',
				inlineLinkText: 'Cat wearing a top hat',
				quoteText: 'Generated image: a quick sketch of a cat wearing a top hat, pencil style.',
				isAppSkill: true
			},
			{
				skillLabel: 'Search',
				appId: 'images',
				previewPath: 'embeds/images/ImagesSearchEmbedPreview',
				fullscreenPath: 'embeds/images/ImagesSearchEmbedFullscreen',
				inlineLinkText: 'Golden Gate Bridge photos',
				quoteText: 'Found 24 images of the Golden Gate Bridge via Brave Image Search.',
				isAppSkill: true
			},
			{
				skillLabel: 'Image Result',
				appId: 'images',
				previewPath: 'embeds/images/ImageResultEmbedPreview',
				fullscreenPath: 'embeds/images/ImageResultEmbedFullscreen',
				inlineLinkText: 'Golden Gate Bridge at sunset — flickr.com',
				quoteText: 'Golden Gate Bridge at sunset, photographed from Marin Headlands.'
			},
			{
				skillLabel: 'Upload',
				appId: 'images',
				previewPath: 'embeds/images/ImageEmbedPreview',
				fullscreenPath: 'embeds/images/ImageEmbedFullscreen',
				inlineLinkText: 'golden-gate-sunset.jpg',
				quoteText: 'Uploaded image: golden-gate-sunset.jpg (2.4 MB, JPEG)'
			},
			{
				skillLabel: 'View',
				appId: 'images',
				previewPath: 'embeds/images/ImageViewEmbedPreview',
				fullscreenPath: 'embeds/images/ImageEmbedFullscreen',
				inlineLinkText: 'View: golden-gate-sunset.jpg',
				quoteText:
					'I analyzed the image: a vibrant sunset photograph taken at the Golden Gate Bridge.',
				isAppSkill: true
			}
		],
		news: [
			{
				skillLabel: 'Article',
				appId: 'news',
				previewPath: 'embeds/news/NewsEmbedPreview',
				fullscreenPath: 'embeds/news/NewsEmbedFullscreen',
				inlineLinkText: 'Svelte 5 officially released',
				quoteText:
					'The latest version of the popular frontend framework brings fundamental changes to reactivity.'
			},
			{
				skillLabel: 'Search',
				appId: 'news',
				previewPath: 'embeds/news/NewsSearchEmbedPreview',
				fullscreenPath: 'embeds/news/NewsSearchEmbedFullscreen',
				inlineLinkText: 'Latest technology news 2026',
				quoteText:
					'New AI-powered development tools are changing how developers write, test, and deploy software.',
				isAppSkill: true
			}
		],
		travel: [
			{
				skillLabel: 'Search',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelSearchEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelSearchEmbedFullscreen',
				inlineLinkText: 'Munich to London, Mar 15',
				quoteText: 'Lufthansa LH2485: Munich to London Heathrow, 2h 10m, from 89 EUR.',
				isAppSkill: true
			},
			{
				skillLabel: 'Connection',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelConnectionEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelConnectionEmbedFullscreen',
				inlineLinkText: 'MUC to LHR direct flight',
				quoteText: 'Direct flight Munich to London, 2h 10min, Terminal 2, Gate B22.'
			},
			{
				skillLabel: 'Price Calendar',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelPriceCalendarEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelPriceCalendarEmbedFullscreen',
				inlineLinkText: 'Munich to Barcelona prices, March',
				quoteText: 'Cheapest day: March 18 at 62 EUR. Prices shown for Munich to Barcelona.',
				isAppSkill: true
			},
			{
				skillLabel: 'Stay',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelStayEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelStayEmbedFullscreen',
				inlineLinkText: 'Hotel Maximilian, Munich',
				quoteText: 'Hotel Maximilian: 4-star hotel in central Munich, from 387 EUR for 3 nights.'
			},
			{
				skillLabel: 'Stays Search',
				appId: 'travel',
				previewPath: 'embeds/travel/TravelStaysEmbedPreview',
				fullscreenPath: 'embeds/travel/TravelStaysEmbedFullscreen',
				inlineLinkText: 'Hotels in Barcelona, Mar 15-18',
				quoteText: 'Found 8 hotels in Barcelona for Mar 15-18. Top pick: Hotel Arts Barcelona.',
				isAppSkill: true
			}
		],
		maps: [
			{
				skillLabel: 'Search',
				appId: 'maps',
				previewPath: 'embeds/maps/MapsSearchEmbedPreview',
				fullscreenPath: 'embeds/maps/MapsSearchEmbedFullscreen',
				inlineLinkText: 'Coffee shops near Marienplatz',
				quoteText: 'Man vs. Machine Coffee Roasters — Rated 4.7, 0.3km from Marienplatz, Munich.',
				isAppSkill: true
			},
			{
				skillLabel: 'Location',
				appId: 'maps',
				previewPath: 'embeds/maps/MapsLocationEmbedPreview',
				fullscreenPath: 'embeds/maps/MapsLocationEmbedFullscreen',
				inlineLinkText: 'Berlin Hauptbahnhof',
				quoteText:
					'Berlin Hauptbahnhof, Europaplatz 1, 10557 Berlin — static map + open-in-maps action.'
			}
		],
		math: [
			{
				skillLabel: 'Calculate',
				appId: 'math',
				previewPath: 'embeds/math/MathCalculateEmbedPreview',
				fullscreenPath: 'embeds/math/MathCalculateEmbedFullscreen',
				inlineLinkText: 'sin(pi/4) + cos(pi/3)',
				quoteText: 'Result: sin(pi/4) + cos(pi/3) = sqrt(2)/2 + 1/2 approx 1.207',
				isAppSkill: true
			},
			{
				skillLabel: 'Plot',
				appId: 'math',
				previewPath: 'embeds/math/MathPlotEmbedPreview',
				fullscreenPath: 'embeds/math/MathPlotEmbedFullscreen',
				inlineLinkText: 'sin(x) and cos(x) plot',
				quoteText: 'Interactive plot of f(x) = sin(x) and f(x) = cos(x) over [-2pi, 2pi].'
			}
		],
		events: [
			{
				skillLabel: 'Event',
				appId: 'events',
				previewPath: 'embeds/events/EventEmbedPreview',
				fullscreenPath: 'embeds/events/EventEmbedFullscreen',
				inlineLinkText: 'AI & ML Berlin Meetup',
				quoteText: 'AI & Machine Learning Berlin Meetup. March 15, 19:00 at Factory Berlin.'
			},
			{
				skillLabel: 'Search',
				appId: 'events',
				previewPath: 'embeds/events/EventsSearchEmbedPreview',
				fullscreenPath: 'embeds/events/EventsSearchEmbedFullscreen',
				inlineLinkText: 'AI meetups in Berlin',
				quoteText: 'Found 3 upcoming AI & tech events in Berlin this month.',
				isAppSkill: true
			}
		],
		reminder: [
			{
				skillLabel: 'Reminder',
				appId: 'reminder',
				previewPath: 'embeds/reminder/ReminderEmbedPreview',
				fullscreenPath: 'embeds/reminder/ReminderEmbedFullscreen',
				inlineLinkText: 'Reminder: tomorrow 9:00 AM',
				quoteText: 'Reminder set! I will send a message in this chat tomorrow at 9:00 AM.',
				isAppSkill: true
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
				inlineLinkText: 'Dr. Mueller appointment — Apr 3',
				quoteText: 'Appointment confirmed with Dr. Mueller on April 3 at 10:30 AM.'
			},
			{
				skillLabel: 'Search',
				appId: 'health',
				previewPath: 'embeds/health/HealthSearchEmbedPreview',
				fullscreenPath: 'embeds/health/HealthSearchEmbedFullscreen',
				inlineLinkText: 'Cardiologists near Munich',
				quoteText: 'Found 5 cardiologists within 5km. Top result: Prof. Weber, rated 4.9.',
				isAppSkill: true
			}
		],
		mail: [
			{
				skillLabel: 'Mail',
				appId: 'mail',
				previewPath: 'embeds/mail/MailEmbedPreview',
				fullscreenPath: 'embeds/mail/MailEmbedFullscreen',
				inlineLinkText: 'Email: Project update from Anna',
				quoteText:
					'The latest sprint review went well. All tickets closed except the auth refactor.'
			}
		],
		pdf: [
			{
				skillLabel: 'PDF',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PDFEmbedPreview',
				fullscreenPath: 'embeds/pdf/PDFEmbedFullscreen',
				inlineLinkText: 'Q4 2025 Report.pdf',
				quoteText: 'Annual revenue increased 23% YoY. Full analysis on pages 4-7.'
			},
			{
				skillLabel: 'Read',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PdfReadEmbedPreview',
				fullscreenPath: 'embeds/pdf/PdfReadEmbedFullscreen',
				inlineLinkText: 'Architecture whitepaper — page 12',
				quoteText:
					'The microservices architecture enables independent scaling of each service component.',
				isAppSkill: true
			},
			{
				skillLabel: 'Search',
				appId: 'pdf',
				previewPath: 'embeds/pdf/PdfSearchEmbedPreview',
				fullscreenPath: 'embeds/pdf/PdfSearchEmbedFullscreen',
				inlineLinkText: 'Search "authentication" in docs',
				quoteText: 'Found 7 mentions of "authentication" across 3 documents.',
				isAppSkill: true
			}
		],
		home: [
			{
				skillLabel: 'Search',
				appId: 'home',
				previewPath: 'embeds/home/HomeSearchEmbedPreview',
				fullscreenPath: 'embeds/home/HomeSearchEmbedFullscreen',
				inlineLinkText: 'Apartments in Berlin',
				quoteText:
					'Found 12 apartments in Berlin. Top pick: 850 EUR/month, 2-room apartment in Kreuzberg.',
				isAppSkill: true
			},
			{
				skillLabel: 'Listing',
				appId: 'home',
				previewPath: 'embeds/home/HomeListingEmbedPreview',
				fullscreenPath: 'embeds/home/HomeListingEmbedFullscreen',
				inlineLinkText: 'Schöne 2-Zimmer-Wohnung in Kreuzberg',
				quoteText: '850 EUR/month — 55 m², 2 rooms, Bergmannstr., Berlin-Kreuzberg'
			}
		],
		nutrition: [
			{
				skillLabel: 'Search',
				appId: 'nutrition',
				previewPath: 'embeds/nutrition/NutritionSearchEmbedPreview',
				fullscreenPath: 'embeds/nutrition/NutritionSearchEmbedFullscreen',
				inlineLinkText: 'Vegetarische Pasta Rezepte',
				quoteText:
					'3 Rezepte gefunden: Spaghetti Aglio e Olio, Penne Arrabiata, Tagliatelle mit Pilzrahmsauce.',
				isAppSkill: true
			},
			{
				skillLabel: 'Recipe',
				appId: 'nutrition',
				previewPath: 'embeds/nutrition/NutritionRecipeEmbedPreview',
				fullscreenPath: 'embeds/nutrition/NutritionRecipeEmbedFullscreen',
				inlineLinkText: 'Spaghetti Aglio e Olio',
				quoteText: 'Spaghetti Aglio e Olio — 25 min, einfach, 4 Portionen.'
			}
		],
		shopping: [
			{
				skillLabel: 'Search',
				appId: 'shopping',
				previewPath: 'embeds/shopping/ShoppingSearchEmbedPreview',
				fullscreenPath: 'embeds/shopping/ShoppingSearchEmbedFullscreen',
				inlineLinkText: 'Wireless headphones under 100 EUR',
				quoteText:
					'Found 12 wireless headphones under 100 EUR. Top pick: Sony WH-1000XM4 at 89 EUR.',
				isAppSkill: true
			},
			{
				skillLabel: 'Result',
				appId: 'shopping',
				previewPath: 'embeds/shopping/ShoppingResultEmbedPreview',
				fullscreenPath: 'embeds/shopping/ShoppingResultEmbedFullscreen',
				inlineLinkText: 'Bio Vollmilch-Joghurt Naturell',
				quoteText: 'Bio Vollmilch-Joghurt Naturell, 500g, 1,39 EUR.'
			}
		]
	};

	/** Maps app ID to its primary SVG icon filename (in /static/icons/) */
	const APP_ICON: Record<string, string> = {
		code: 'coding',
		docs: 'docs',
		web: 'web',
		videos: 'videos',
		images: 'camera',
		news: 'news',
		travel: 'travel',
		maps: 'maps',
		math: 'math',
		events: 'event',
		reminder: 'reminder',
		sheets: 'sheets',
		audio: 'audio',
		health: 'heart',
		mail: 'mail',
		pdf: 'pdf',
		shopping: 'shopping',
		home: 'home',
		nutrition: 'nutrition'
	};

	const ALL_APPS = [
		'code',
		'docs',
		'web',
		'videos',
		'images',
		'news',
		'travel',
		'maps',
		'math',
		'events',
		'reminder',
		'sheets',
		'audio',
		'health',
		'mail',
		'pdf',
		'shopping',
		'home',
		'nutrition'
	];

	// ─── Glob maps ────────────────────────────────────────────────────

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
	for (const k of Object.keys(componentModules)) {
		componentKeyMap.set(extractCleanPath(k).replace('.svelte', ''), k);
	}
	const previewKeyMap = new Map<string, string>();
	for (const k of Object.keys(previewModules)) {
		previewKeyMap.set(extractCleanPath(k).replace('.preview.ts', ''), k);
	}

	// ─── Route state ──────────────────────────────────────────────────

	let currentApp = $derived(page.params.app || 'code');
	let sections = $derived(APP_REGISTRY[currentApp] ?? []);
	let isUnknownApp = $derived(!(currentApp in APP_REGISTRY));

	// ─── Global toolbar ───────────────────────────────────────────────

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

	// ─── Per-section loaded state ─────────────────────────────────────
	// Each section loads its preview + fullscreen components and mock props.
	// Components are stored as Svelte constructor refs and rendered
	// declaratively in the template via <Preview {...props} />.

	interface LoadedSection {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		PreviewComponent: any;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		FullscreenComponent: any;
		loadError: string | null;
		isLoading: boolean;
		mockProps: Record<string, unknown>;
		variants: Record<string, Record<string, unknown>>;
		hasPreviewFile: boolean;
		fullscreenMockProps: Record<string, unknown>;
		fullscreenVariants: Record<string, Record<string, unknown>>;
		hasFullscreenPreviewFile: boolean;
		activeVariant: string;
		propsJson: string;
		propsError: string | null;
		showPropsEditor: boolean;
		/** Index of the currently shown variant in fullscreen & large-slideshow */
		fullscreenVariantIndex: number;
		/** Index of the currently shown slide in large-group slideshow */
		largeSlideIndex: number;
	}

	let loadedSections = $state<LoadedSection[]>([]);

	// Track the last app we initialized for, to avoid re-running on unrelated changes.
	let lastInitApp = '';

	// Re-initialise when app changes. We compare against lastInitApp to ensure
	// the $effect only fires on actual app-slug changes, not on loadedSections writes.
	$effect(() => {
		const app = currentApp; // reactive dependency: the route param
		if (app === lastInitApp) return;
		lastInitApp = app;

		const snap = APP_REGISTRY[app] ?? [];
		loadedSections = snap.map(() => ({
			PreviewComponent: null,
			FullscreenComponent: null,
			loadError: null,
			isLoading: true,
			mockProps: {},
			variants: {},
			hasPreviewFile: false,
			fullscreenMockProps: {},
			fullscreenVariants: {},
			hasFullscreenPreviewFile: false,
			activeVariant: 'default',
			propsJson: '{}',
			propsError: null,
			showPropsEditor: false,
			fullscreenVariantIndex: 0,
			largeSlideIndex: 0
		}));

		// Fire async loaders. We run them SEQUENTIALLY (not in parallel) to avoid
		// a Svelte 5 reactivity race: when multiple loaders complete concurrently
		// and each replaces `loadedSections` with a spread-copy, the intermediate
		// proxy swaps can leave one section stuck in the visible "Loading..."
		// state while its `isLoading` flag has already been flipped to false
		// (contradictory DOM). See Linear OPE-405 follow-up (Phase 1 flake).
		//
		// We do NOT block this effect on the loaders — we kick off an async IIFE.
		// Sequential loading trades a tiny bit of initial latency for deterministic
		// reactivity. For most apps there are only 1–4 sections, so the cost is
		// negligible (dynamic imports are already hot in the module graph after
		// the first app is visited).
		(async () => {
			for (let i = 0; i < snap.length; i++) {
				await loadSection(snap[i], i);
			}
		})();
	});

	async function loadSection(section: EmbedSection, idx: number) {
		const prevKey = previewKeyMap.get(section.previewPath) ?? '';
		const fullscreenPrevKey = previewKeyMap.get(section.fullscreenPath) ?? '';
		const previewKey = componentKeyMap.get(section.previewPath) ?? '';
		const fullscreenKey = componentKeyMap.get(section.fullscreenPath) ?? '';

		// After await, Svelte does NOT track reads as $effect dependencies.
		// So reading loadedSections[idx] here is safe.
		try {
			if (!previewKey) throw new Error(`Component not found: ${section.previewPath}.svelte`);

			const [previewMod, fullscreenMod] = await Promise.all([
				componentModules[previewKey](),
				fullscreenKey ? componentModules[fullscreenKey]() : Promise.resolve(null)
			]);

			// Read from the $state proxy AFTER await — writes go through proxy
			// and trigger template updates automatically.
			const s = loadedSections[idx];
			if (!s) return;

			s.PreviewComponent = previewMod?.default ?? null;
			s.FullscreenComponent = (fullscreenMod as { default?: unknown } | null)?.default ?? null;

			if (prevKey && previewModules[prevKey]) {
				try {
					const preview = await previewModules[prevKey]();
					s.mockProps = preview.default ?? {};
					s.variants = preview.variants ?? {};
					s.hasPreviewFile = true;
					s.propsJson = JSON.stringify(preview.default ?? {}, null, 2);
				} catch {
					/* no preview data — component renders with {} */
				}
			}

			if (fullscreenPrevKey && previewModules[fullscreenPrevKey]) {
				try {
					const fullscreenPreview = await previewModules[fullscreenPrevKey]();
					s.fullscreenMockProps = fullscreenPreview.default ?? {};
					s.fullscreenVariants = fullscreenPreview.variants ?? {};
					s.hasFullscreenPreviewFile = true;
				} catch {
					/* no fullscreen preview data — fullscreen uses preview props */
				}
			}

			// IMPORTANT: Flip isLoading to false as the LAST mutation. We no
			// longer do `loadedSections = [...loadedSections]` because the
			// spread-copy introduces a proxy-swap race that can freeze the
			// `section-loading` DOM element while other sub-mutations on this
			// proxy have already committed. The proxy mutation below is
			// sufficient to trigger the template update on its own.
			s.isLoading = false;
		} catch (err) {
			const s = loadedSections[idx];
			if (!s) return;
			s.loadError = err instanceof Error ? err.message : String(err);
			s.isLoading = false;
		}
	}

	/**
	 * Returns ordered list of [name, props] pairs for all "data-showing" variants.
	 * Excludes: 'error', 'mobile', 'processing' — includes 'default' + the rest.
	 * Used for Group — Small, Group — Large (slideshow), and Fullscreen cycling.
	 */
	const DATA_VARIANT_EXCLUDE = new Set(['error', 'mobile', 'processing']);

	function buildDataVariants(
		baseProps: Record<string, unknown>,
		variants: Record<string, Record<string, unknown>>
	): Array<[string, Record<string, unknown>]> {
		const result: Array<[string, Record<string, unknown>]> = [['default', baseProps]];
		for (const [name, v] of Object.entries(variants)) {
			if (!DATA_VARIANT_EXCLUDE.has(name)) {
				result.push([name, { ...baseProps, ...v }]);
			}
		}
		return result;
	}

	function getDataVariants(s: LoadedSection): Array<[string, Record<string, unknown>]> {
		return buildDataVariants(s.mockProps, s.variants);
	}

	function getFullscreenDataVariants(s: LoadedSection): Array<[string, Record<string, unknown>]> {
		if (s.hasFullscreenPreviewFile) {
			return buildDataVariants(s.fullscreenMockProps, s.fullscreenVariants);
		}
		return getDataVariants(s);
	}

	/**
	 * Top-level prop names that fullscreen components receive directly (NOT wrapped in `data`).
	 * These are common to ALL fullscreen components per EmbedFullscreenCommonProps.
	 */
	const FULLSCREEN_TOP_LEVEL_PROPS = new Set([
		'onClose',
		'embedId',
		'hasPreviousEmbed',
		'hasNextEmbed',
		'onNavigatePrevious',
		'onNavigateNext',
		'navigateDirection',
		'showChatButton',
		'onShowChat',
		'data'
	]);

	/**
	 * Direct-prop names used by child-detail fullscreens that DON'T use the data-driven shape.
	 * E.g., ShoppingResultEmbedFullscreen takes `product`, NutritionRecipeEmbedFullscreen takes `recipe`.
	 * If any of these keys is present in raw props, the fullscreen is treated as a direct-props
	 * component and no wrapping is applied.
	 *
	 * IMPORTANT: Only add names here for fullscreens that genuinely accept a direct entity prop
	 * (not `data: EmbedFullscreenRawData`). After the OPE-276 data-driven migration, most child
	 * fullscreens were migrated to `data.decodedContent` — their old direct-prop names were
	 * removed in OPE-413 to prevent wrapFullscreenProps from bypassing the wrapping.
	 */
	const DIRECT_PROP_NAMES = new Set([
		'product',
		'recipe',
	]);

	/**
	 * Fullscreen component paths that NEVER use the data-driven shape — they take
	 * flat props directly. These were not migrated in OPE-276 (data-driven routing).
	 * Listed here so the wrapper passes their preview props through untouched.
	 */
	const NEVER_WRAP_FULLSCREEN_PATHS = new Set([
		'embeds/news/NewsEmbedFullscreen',
		'embeds/pdf/PdfReadEmbedFullscreen',
		'embeds/pdf/PdfSearchEmbedFullscreen'
	]);

	/**
	 * Wrap legacy preview-file fullscreen props into the data-driven shape required
	 * by post-OPE-276 fullscreen components.
	 *
	 * Legacy preview files export flat content props like { query, provider, results }.
	 * Post-OPE-276 fullscreens require { data: { decodedContent: {...}, embedData: {...} } }.
	 *
	 * Detection rules:
	 * - If `data` already exists → component already uses new shape, pass through
	 * - If any DIRECT_PROP_NAMES key exists → child-detail fullscreen, pass through
	 * - Otherwise → wrap content fields into `data.decodedContent` and pass through
	 *   common navigation props at top level
	 */
	function wrapFullscreenProps(
		rawProps: Record<string, unknown>,
		section: EmbedSection
	): Record<string, unknown> {
		// Already in new shape — pass through
		if ('data' in rawProps) return rawProps;

		// Explicit opt-out: fullscreen not migrated to data-driven shape
		if (NEVER_WRAP_FULLSCREEN_PATHS.has(section.fullscreenPath)) return rawProps;

		// Direct-prop fullscreen (e.g., ShoppingResultEmbedFullscreen takes `product`).
		// Only match when the value is a non-null object — string/empty values for
		// fields like `image: ""` must not trigger direct-prop pass-through, since
		// those are usually legitimate OG-metadata on a wrapped preview (OPE-405).
		for (const key of Object.keys(rawProps)) {
			if (!DIRECT_PROP_NAMES.has(key)) continue;
			const val = rawProps[key];
			if (val !== null && typeof val === 'object') return rawProps;
		}

		// Legacy flat props — wrap into data-driven shape
		const decodedContent: Record<string, unknown> = {};
		const topLevel: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(rawProps)) {
			if (FULLSCREEN_TOP_LEVEL_PROPS.has(k)) {
				topLevel[k] = v;
			} else {
				decodedContent[k] = v;
			}
		}
		const status = decodedContent.status as string | undefined;
		return {
			...topLevel,
			data: {
				decodedContent,
				embedData: { status: status || 'finished' },
				attrs: { app_id: section.appId }
			}
		};
	}

	function getEffectiveProps(s: LoadedSection): Record<string, unknown> {
		const base = { ...s.mockProps };
		if (s.activeVariant !== 'default' && s.variants[s.activeVariant]) {
			Object.assign(base, s.variants[s.activeVariant]);
		}
		return base;
	}

	function selectVariant(idx: number, name: string) {
		const s = loadedSections[idx];
		if (!s) return;
		s.activeVariant = name;
		s.propsJson = JSON.stringify(getEffectiveProps(s), null, 2);
		s.propsError = null;
		loadedSections = [...loadedSections];
	}

	function handlePropsInput(idx: number, value: string) {
		const s = loadedSections[idx];
		if (!s) return;
		s.propsJson = value;
		try {
			const parsed = JSON.parse(value);
			if (typeof parsed === 'object' && parsed !== null) {
				s.mockProps = { ...s.mockProps, ...parsed };
				s.propsError = null;
			}
		} catch (err) {
			s.propsError = err instanceof Error ? err.message : 'Invalid JSON';
		}
		loadedSections = [...loadedSections];
	}

	function resetProps(idx: number) {
		const s = loadedSections[idx];
		if (!s) return;
		s.propsJson = JSON.stringify(getEffectiveProps(s), null, 2);
		s.propsError = null;
		loadedSections = [...loadedSections];
	}
</script>

<div class="showcase-page">
	<!-- App switcher bar -->
	<header class="app-switcher">
		<a href="/dev/preview" class="back-link">&#8592; All</a>
		<nav class="app-pills" aria-label="Switch embed app">
			{#each ALL_APPS as appSlug}
				<a
					class="app-pill"
					class:active={appSlug === currentApp}
					href="/dev/preview/embeds/{appSlug}">{appSlug}</a
				>
			{/each}
		</nav>
		<div class="toolbar-right">
			<button class="theme-btn" data-testid="theme-toggle-btn" onclick={toggleTheme} title="Toggle theme">
				{$theme === 'light' ? '🌙' : '☀️'}
			</button>
			<div class="bg-group">
				<button
					class="ctrl-btn"
					class:active={background === 'auto'}
					onclick={() => (background = 'auto')}>Auto</button
				>
				<button
					class="ctrl-btn"
					class:active={background === 'grid'}
					onclick={() => (background = 'grid')}>Grid</button
				>
			</div>
		</div>
	</header>

	<!-- Scrollable content -->
	<div class="showcase-body" data-testid="showcase-body" style={backgroundStyle}>
		{#if isUnknownApp}
			<div class="unknown-app" data-testid="unknown-app">
				<h2>Unknown app: "{currentApp}"</h2>
				<p>Available: {ALL_APPS.join(', ')}</p>
			</div>
		{:else}
			<div class="app-heading">
				<h1 class="app-title" data-testid="app-title">{currentApp}</h1>
				<span class="section-count">{sections.length} skill{sections.length !== 1 ? 's' : ''}</span>
			</div>

			{#each sections as section, si}
				{@const s = loadedSections[si]}

				<section class="skill-section" data-testid="skill-section">
					<div class="skill-header">
						<h2 class="skill-label" data-testid="skill-label">{section.skillLabel}</h2>
						{#if s && !s.isLoading && !s.loadError}
							<div class="skill-actions">
								{#if Object.keys(s.variants).length > 0}
									<div class="template-row">
										<span class="template-label">Template:</span>
										<button
											class="tmpl-btn"
											class:active={s.activeVariant === 'default'}
											onclick={() => selectVariant(si, 'default')}>Default</button
										>
										{#each Object.keys(s.variants).filter((v) => v !== 'mobile') as vname}
											<button
												class="tmpl-btn"
												class:active={s.activeVariant === vname}
												onclick={() => selectVariant(si, vname)}>{vname}</button
											>
										{/each}
									</div>
								{/if}
								<button
									class="props-btn"
									class:active={s.showPropsEditor}
									onclick={() => {
										s.showPropsEditor = !s.showPropsEditor;
										loadedSections = [...loadedSections];
									}}>Props</button
								>
							</div>
						{/if}
					</div>

					{#if !s || s.isLoading}
						<p class="section-loading" data-testid="section-loading">Loading {section.skillLabel}...</p>
					{:else if s.loadError}
						<p class="section-error" data-testid="section-error">{s.loadError}</p>
					{:else}
						<!-- Svelte 5 error boundary: if a display-type render throws (e.g. a
						     component threw during mount or a destructure hit undefined), we
						     must capture and display it — otherwise the error is swallowed
						     silently and the section-loading DOM from the previous reactive
						     pass stays in place, leaving a stuck section (Linear OPE-405). -->
						<svelte:boundary
							onerror={(error) => {
								console.error(`[preview-page] Section "${section.skillLabel}" render error:`, error);
								const msg = error instanceof Error ? error.message : String(error);
								// Record the error on the section so the next reactive pass
								// shows the section-error branch instead of retrying.
								const cur = loadedSections[si];
								if (cur && !cur.loadError) {
									cur.loadError = `Render error: ${msg}`;
								}
							}}
						>
							{#snippet failed(error)}
								<p class="section-error" data-testid="section-error">
									Render error: {error instanceof Error ? error.message : String(error)}
								</p>
							{/snippet}
						<!-- Props editor -->
						{#if s.showPropsEditor}
							<div class="props-panel">
								<div class="props-panel-hdr">
									<span class="props-panel-title">Props JSON</span>
									<button class="reset-btn" onclick={() => resetProps(si)}>Reset</button>
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

						<!-- 1. Inline Link (simulated) -->
						<div class="dt">
							<h3 class="dt-heading" data-testid="dt-heading">Inline Link</h3>
							<div class="dt-body dt-body--inline">
								<span class="inline-ctx">The assistant found </span>
								<span class="fake-inline">
									<Icon
										name={APP_ICON[section.appId] ?? section.appId}
										type="app"
										size="20px"
										className="showcase-app-icon no-fade"
										noMargin={true}
										noAnimation={true}
									/>
									<span class="fake-link-text">{section.inlineLinkText}</span>
								</span>
								<span class="inline-ctx"> for you.</span>
							</div>
						</div>

						<!-- 2. Quote Block (simulated) -->
						<div class="dt">
							<h3 class="dt-heading" data-testid="dt-heading">Quote Block</h3>
							<div class="dt-body">
								<blockquote
									class="fake-quote"
									style="border-left-color: var(--color-app-{section.appId}-start, var(--color-primary-start))"
								>
									<p class="fake-quote-text">{section.quoteText}</p>
									<footer class="fake-quote-footer">
										<Icon
											name={APP_ICON[section.appId] ?? section.appId}
											type="app"
											size="18px"
											className="showcase-app-icon no-fade"
											noMargin={true}
											noAnimation={true}
										/>
										<span class="fake-source">{section.appId}</span>
									</footer>
								</blockquote>
							</div>
						</div>

						<!-- 3. Group — Small + 4. Group — Large -->
						{#if s.PreviewComponent}
							{@const Preview = s.PreviewComponent}
							{@const dataVars = getDataVariants(s)}

							<!-- 3. Group — Small (horizontal scroll of all data variants) -->
							{#if dataVars.length > 0}
								<div class="dt">
									<h3 class="dt-heading" data-testid="dt-heading">
										Group — Small <span class="size-hint"
											>{dataVars.length} variant{dataVars.length !== 1 ? 's' : ''} · horizontal scroll</span
										>
									</h3>
									<div class="dt-body dt-body--flush dt-body--group-small">
										<div class="group-scroll-row">
											{#each dataVars as [vname, vprops]}
												<div class="group-scroll-item">
													<div class="group-variant-label">{vname}</div>
													<Preview {...vprops} isMobile={false} />
												</div>
											{/each}
										</div>
									</div>
								</div>
							{/if}

							<!-- 4. Group — Large (slideshow of all data variants) — hidden for app skills -->
							{#if dataVars.length > 1 && !section.isAppSkill}
								{@const totalSlides = dataVars.length}
								{@const slideIdx = s.largeSlideIndex}
								{@const [, slideProps] = dataVars[slideIdx]}
								<div class="dt">
									<h3 class="dt-heading" data-testid="dt-heading">
										Group — Large <span class="size-hint"
											>{dataVars.length} variants · slideshow</span
										>
									</h3>
									<div class="dt-body dt-body--flush">
										<div class="large-slideshow-wrapper">
											<!-- Slide indicator + arrows (above the container, like EmbedPreviewLarge carousel) -->
											<div class="slideshow-controls slideshow-controls--top">
												<button
													class="slide-arrow"
													aria-label="Previous"
													onclick={() => {
														s.largeSlideIndex = (slideIdx - 1 + totalSlides) % totalSlides;
														loadedSections = [...loadedSections];
													}}
												>
													&#8592;
												</button>
												<span class="slide-label"
													>{dataVars[slideIdx][0]}
													<span class="slide-count">{slideIdx + 1} / {totalSlides}</span></span
												>
												<button
													class="slide-arrow"
													aria-label="Next"
													onclick={() => {
														s.largeSlideIndex = (slideIdx + 1) % totalSlides;
														loadedSections = [...loadedSections];
													}}
												>
													&#8594;
												</button>
											</div>
											<div class="large-container">
												<Preview {...slideProps} isMobile={false} />
											</div>
										</div>
									</div>
								</div>
							{/if}
						{/if}

						<!-- 6. Fullscreen (clipped inline, cycles through data variants) -->
						{#if s.FullscreenComponent}
							{@const Fullscreen = s.FullscreenComponent}
							{@const dataVars2 = getFullscreenDataVariants(s)}
							{@const fsIdx = s.fullscreenVariantIndex}
							{@const [_fsVname, fsRawProps] = dataVars2[fsIdx]}
							{@const fsProps = wrapFullscreenProps(fsRawProps, section)}
							{@const fsTotal = dataVars2.length}
							<div class="dt">
								<h3 class="dt-heading" data-testid="dt-heading">
									Fullscreen <span class="size-hint"
										>clipped inline · {fsTotal} variant{fsTotal !== 1 ? 's' : ''}</span
									>
								</h3>
								<div class="dt-body dt-body--flush">
									<!-- Variant label bar above fullscreen -->
									{#if fsTotal > 1}
										<div class="fs-variant-bar">
											{#each dataVars2 as [vname], vi}
												<button
													class="fs-var-btn"
													class:active={vi === fsIdx}
													onclick={() => {
														s.fullscreenVariantIndex = vi;
														loadedSections = [...loadedSections];
													}}>{vname}</button
												>
											{/each}
										</div>
									{/if}
									<div class="fs-clip" data-testid="fs-clip">
										{#key fsIdx}
											<Fullscreen
												{...fsProps}
												onClose={() => {}}
												hasPreviousEmbed={fsTotal > 1 && fsIdx > 0}
												hasNextEmbed={fsTotal > 1 && fsIdx < fsTotal - 1}
												onNavigatePrevious={() => {
													s.fullscreenVariantIndex = Math.max(0, fsIdx - 1);
													loadedSections = [...loadedSections];
												}}
												onNavigateNext={() => {
													s.fullscreenVariantIndex = Math.min(fsTotal - 1, fsIdx + 1);
													loadedSections = [...loadedSections];
												}}
											/>
										{/key}
									</div>
								</div>
							</div>
						{/if}
						</svelte:boundary>
					{/if}
				</section>
			{/each}
		{/if}
	</div>
</div>

<style>
	.showcase-page {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary);
	}

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
	.back-link:hover {
		text-decoration: underline;
	}

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
	.app-pills::-webkit-scrollbar {
		display: none;
	}

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
		transition:
			background-color 0.15s,
			color 0.15s;
	}
	.app-pill:hover {
		background: var(--color-grey-25);
		color: var(--color-font-primary);
	}
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
	.ctrl-btn:last-child {
		border-right: none;
	}
	.ctrl-btn:hover {
		background: var(--color-grey-20);
	}
	.ctrl-btn.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional: always white on active toggle */
	}

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

	.skill-section {
		margin-bottom: 64px;
		padding-bottom: 48px;
		border-bottom: 1px solid var(--color-grey-25);
		/* Match the effective embed container width in real chat:
		   chat-history-content is --chat-content-max-width (1000px),
		   message-align-left is calc(100% - 70px) within that. */
		max-width: calc(var(--chat-content-max-width, 1000px) - 70px);
		overflow-x: auto;
	}
	.skill-section:last-child {
		border-bottom: none;
		margin-bottom: 0;
	}

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
	.tmpl-btn:hover:not(.active) {
		background: var(--color-grey-20);
	}
	.tmpl-btn.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional */
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
	.props-btn:hover {
		background: var(--color-grey-20);
		color: var(--color-font-primary);
	}
	.props-btn.active {
		background: var(--color-grey-25);
		color: var(--color-font-primary);
	}

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
	.props-panel-title {
		font-size: 0.8125rem;
		font-weight: 600;
	}
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
	.reset-btn:hover {
		background: var(--color-grey-20);
		color: var(--color-font-primary);
	}
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
		box-sizing: border-box;
	}
	.props-editor:focus {
		border-color: var(--color-primary-start);
	}
	.props-error {
		font-size: 0.6875rem;
		color: var(--color-error, #e53935);
		margin: 0;
	}

	.dt {
		margin-bottom: 36px;
	}

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

	.dt-body--inline {
		font-size: 0.9375rem;
		line-height: 1.6;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 3px;
	}
	.inline-ctx {
		color: var(--color-font-primary);
	}

	.fake-inline {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	:global(.showcase-app-icon) {
		display: inline-flex;
	}
	.fake-link-text {
		font-size: 0.9375rem;
		font-weight: 500;
		color: var(--color-primary-start);
	}

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
	.fake-source {
		font-size: 0.75rem;
		color: var(--color-font-tertiary);
	}

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
		/* 425px ensures preview-large BasicInfosBar is fully visible (card 400px + 15px protrusion + buffer) */
		min-height: 425px;
		border-radius: 12px;
		overflow: visible;
		border: 1px solid var(--color-grey-25);
		max-width: 100%;
	}

	.fs-clip {
		position: relative;
		width: 100%;
		height: 560px;
		overflow: hidden;
		isolation: isolate;
		border-radius: 12px;
		border: 1px solid var(--color-grey-25);
	}

	.section-loading {
		padding: 24px 0;
		color: var(--color-font-tertiary);
		font-size: 0.875rem;
	}
	.section-error {
		padding: 16px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-error, #e53935);
		border-radius: 8px;
		color: var(--color-error, #e53935);
		font-size: 0.875rem;
		font-family: 'Courier New', monospace;
	}

	.unknown-app {
		padding: 48px 0;
		text-align: center;
		color: var(--color-font-tertiary);
	}
	.unknown-app h2 {
		font-size: 1.25rem;
		margin: 0 0 8px;
	}
	.unknown-app p {
		font-size: 0.875rem;
		margin: 0;
	}

	/* ── Group — Small: horizontal scroll row ───────────────────────────────── */
	.dt-body--group-small {
		padding: 12px 16px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-grey-25);
		border-radius: 12px;
		overflow-x: auto;
	}

	.group-scroll-row {
		display: flex;
		gap: 12px;
		overflow-x: auto;
		padding-bottom: 8px;
		align-items: flex-start;
		scrollbar-width: thin;
		scrollbar-color: var(--color-grey-40) transparent;
	}

	.group-scroll-row::-webkit-scrollbar {
		height: 4px;
	}
	.group-scroll-row::-webkit-scrollbar-track {
		background: transparent;
	}
	.group-scroll-row::-webkit-scrollbar-thumb {
		background: var(--color-grey-40);
		border-radius: 2px;
	}

	.group-scroll-item {
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex-shrink: 0;
	}

	.group-variant-label {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-font-tertiary);
		text-align: center;
	}

	/* ── Group — Large: slideshow wrapper ───────────────────────────────────── */
	.large-slideshow-wrapper {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.slideshow-controls {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 14px 16px 4px;
	}

	.slideshow-controls--top {
		padding: 4px 16px 12px;
	}

	.slide-arrow {
		padding: 4px 12px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 1rem;
		cursor: pointer;
		line-height: 1;
		transition: background-color 0.15s;
	}
	.slide-arrow:hover {
		background: var(--color-grey-20);
	}

	.slide-label {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-font-primary);
		min-width: 120px;
		text-align: center;
	}

	.slide-count {
		font-weight: 400;
		color: var(--color-font-tertiary);
		font-size: 0.75rem;
	}

	/* ── Fullscreen variant bar ──────────────────────────────────────────────── */
	.fs-variant-bar {
		display: flex;
		gap: 6px;
		padding: 10px 12px;
		background: var(--color-grey-10);
		border: 1px solid var(--color-grey-25);
		border-bottom: none;
		border-radius: 12px 12px 0 0;
		flex-wrap: wrap;
	}

	.fs-var-btn {
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
	.fs-var-btn:hover:not(.active) {
		background: var(--color-grey-20);
	}
	.fs-var-btn.active {
		background: var(--color-primary-start);
		color: #fff; /* intentional */
		border-color: var(--color-primary-start);
	}

	/* When variant bar is present, attach to top of fs-clip */
	.fs-variant-bar + .fs-clip {
		border-radius: 0 0 12px 12px;
	}
</style>
