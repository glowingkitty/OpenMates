/**
 * Embed text renderer registry.
 *
 * Maps embed registry keys (same keys as EMBED_PREVIEW_COMPONENTS) to pure
 * text renderer functions. Each function converts decoded TOON content to
 * human-readable plain text — no ANSI codes, no HTML, no Svelte.
 *
 * Used by:
 *   - Copy-to-clipboard (text/plain MIME)
 *   - Markdown chat export (.md download)
 *   - CLI terminal output (via wrapper in openmates-cli)
 *
 * When adding a new embed type:
 *   1. Create a text renderer in the embed's component folder (e.g. web/webEmbedText.ts)
 *   2. Add the registry key → function mapping here
 *   3. Update docs/contributing/guides/add-embed-type.md checklist
 *
 * Architecture doc: docs/architecture/embeds.md
 */

// ── Shared helpers (exported for use by per-domain renderers) ────────────

/** Extract a non-empty string or return null */
export const str = (v: unknown): string | null =>
	typeof v === 'string' && v.length > 0 ? v : null;

/** Truncate a string with ellipsis */
export function trunc(s: string, max: number): string {
	return s.length > max ? s.slice(0, max) + '…' : s;
}

/** Format a price with currency */
export function formatPrice(amount: unknown, currency: unknown): string {
	if (amount === null || amount === undefined) return '';
	const cur = str(currency)?.toUpperCase() ?? '';
	return cur ? `${cur} ${amount}` : String(amount);
}

/** Parse embed_ids field (pipe-separated string or array) to count */
export function resolveResultCount(c: Record<string, unknown>): number | null {
	if (typeof c.result_count === 'number') return c.result_count;
	const embedIds = c.embed_ids;
	if (typeof embedIds === 'string') return embedIds.split('|').filter(Boolean).length;
	if (Array.isArray(embedIds)) return embedIds.length;
	return null;
}

// ── Per-domain renderer imports ──────────────────────────────────────────

import { renderWebSearch, renderWebRead, renderWebsite } from '../components/embeds/web/webEmbedText';
import { renderTravelConnections, renderTravelStays, renderPriceCalendar, renderFlight, renderConnection, renderStay } from '../components/embeds/travel/travelEmbedText';
import { renderApplication, renderCode, renderCodeDocs, renderCodeRepo, renderCodeRepoSearch } from '../components/embeds/code/codeEmbedText';
import { renderVideosSearch, renderVideoTranscript, renderVideoGenerate, renderVideoCreate, renderVideo } from '../components/embeds/videos/videoEmbedText';
import { renderImageGenerate, renderImagesSearch, renderImage, renderImageResult } from '../components/embeds/images/imageEmbedText';
import { renderMapsSearch, renderMapsPlace } from '../components/embeds/maps/mapsEmbedText';
import { renderEventsSearch, renderEvent } from '../components/embeds/events/eventsEmbedText';
import { renderMailSearch, renderEmail } from '../components/embeds/mail/mailEmbedText';
import { renderHealthSearch, renderAppointment } from '../components/embeds/health/healthEmbedText';
import { renderHomeSearch, renderListing } from '../components/embeds/home/homeEmbedText';
import { renderSheet } from '../components/embeds/sheets/sheetsEmbedText';
import { renderPdf } from '../components/embeds/pdf/pdfEmbedText';
import { renderRecording, renderAudioTranscribe } from '../components/embeds/audio/audioEmbedText';
import { renderMusicGenerate } from '../components/embeds/music/musicEmbedText';
import { renderMathCalculate, renderMathPlot } from '../components/embeds/math/mathEmbedText';
import { renderReminder } from '../components/embeds/reminder/reminderEmbedText';
import { renderShoppingSearch, renderShoppingProduct } from '../components/embeds/shopping/shoppingEmbedText';
import { renderElectronicsSearch, renderElectronicsComponent } from '../components/embeds/electronics/electronicsEmbedText';
import { renderNutritionSearch, renderNutritionRecipe } from '../components/embeds/nutrition/nutritionEmbedText';
import { renderNewsSearch } from '../components/embeds/news/newsEmbedText';
import { renderDoc } from '../components/embeds/docs/docsEmbedText';
import { renderSocialMediaGetPosts, renderSocialMediaPost, renderSocialMediaSearch } from '../components/embeds/social_media/socialMediaEmbedText';
import { renderWeatherDay, renderWeatherForecast, renderWeatherRainRadar } from '../components/embeds/weather/weatherEmbedText';

// ── Renderer type ────────────────────────────────────────────────────────

type EmbedTextRenderer = (
	content: Record<string, unknown>,
	children?: Record<string, unknown>[]
) => string;

function renderGenericAppSkill(content: Record<string, unknown>): string {
	const appId = str(content.app_id) ?? 'app';
	const skillId = str(content.skill_id) ?? 'skill';
	const lines = [`**${appId} | ${skillId}**`];
	const keys = ['query', 'prompt', 'title', 'summary', 'result_count', 'provider', 'status'];

	for (const key of keys) {
		const value = content[key];
		if (value !== null && value !== undefined && typeof value !== 'object') {
			lines.push(`${key}: ${trunc(String(value), 120)}`);
		}
	}

	return lines.join('\n');
}

// ── Registry ─────────────────────────────────────────────────────────────

/**
 * Maps embed registry keys to text renderer functions.
 * Keys match EMBED_PREVIEW_COMPONENTS in embedRegistry.generated.ts.
 */
export const EMBED_TEXT_RENDERERS: Record<string, EmbedTextRenderer> = {
	// ── App-skill-use (composite) embeds ──────────────────────────────
	'app:web:search': renderWebSearch,
	'app:web:read': renderWebRead,
	'app:news:search': renderNewsSearch,
	'app:shopping:search_products': renderShoppingSearch,
	'app:electronics:search_components': renderElectronicsSearch,
	'app:nutrition:search_recipes': renderNutritionSearch,
	'app:events:search': renderEventsSearch,
	'app:videos:search': renderVideosSearch,
	'app:videos:generate': renderVideoGenerate,
	'app:videos:create': renderVideoCreate,
	'app:videos:get_transcript': renderVideoTranscript,
	'app:maps:search': renderMapsSearch,
	'app:code:search_repos': renderCodeRepoSearch,
	'app:code:get_docs': renderCodeDocs,
	'app:code:run': renderGenericAppSkill,
	'app:code:clean_repo': renderGenericAppSkill,
	'app:code:get_issues': renderGenericAppSkill,
	'app:code:add_issue': renderGenericAppSkill,
	'app:code:remove_secrets': renderGenericAppSkill,
	'app:code:get_project_overview': renderGenericAppSkill,
	'app:travel:search_connections': renderTravelConnections,
	'app:travel:search_stays': renderTravelStays,
	'app:travel:price_calendar': renderPriceCalendar,
	'app:travel:get_flight': renderFlight,
	'app:images:generate': renderImageGenerate,
	'app:images:generate_draft': renderImageGenerate,
	'app:images:search': renderImagesSearch,
	'app:images:view': renderImage,
	'app:images:vectorize': renderGenericAppSkill,
	'app:music:generate': renderMusicGenerate,
	'app:health:search_appointments': renderHealthSearch,
	'app:health:create_report': renderGenericAppSkill,
	'app:home:search': renderHomeSearch,
	'app:books:translate': renderGenericAppSkill,
	'app:fitness:search_locations_and_courses': renderGenericAppSkill,
	'app:openmates:share-usecase': renderGenericAppSkill,
	'app:openmates:get-docs': renderGenericAppSkill,
	'app:openmates:search-docs': renderGenericAppSkill,
	'app:pdf:read': renderGenericAppSkill,
	'app:pdf:search': renderGenericAppSkill,
	'app:pdf:view': renderGenericAppSkill,
	'app:mail:search': renderMailSearch,
	'app:math:calculate': renderMathCalculate,
	'app:reminder:set-reminder': renderReminder,
	'app:reminder:list-reminders': renderReminder,
	'app:reminder:cancel-reminder': renderReminder,
	'app:audio:transcribe': renderAudioTranscribe,
	'app:social_media:get-posts': renderSocialMediaGetPosts,
	'app:social_media:search': renderSocialMediaSearch,
	'app:weather:forecast': renderWeatherForecast,
	'app:weather:rain_radar': renderWeatherRainRadar,

	// ── Direct embeds ────────────────────────────────────────────────
	'web-website': renderWebsite,
	'code-code': renderCode,
	'code-application': renderApplication,
	'code-repo': renderCodeRepo,
	'docs-doc': renderDoc,
	'sheets-sheet': renderSheet,
	'pdf': renderPdf,
	'image': renderImage,
	'images-image-result': renderImageResult,
	'videos-video': renderVideo,
	'travel-connection': renderConnection,
	'travel-stay': renderStay,
	'maps-place': renderMapsPlace,
	'maps': renderMapsPlace,
	'recording': renderRecording,
	'mail-email': renderEmail,
	'math-plot': renderMathPlot,
	'events-event': renderEvent,
	'health-appointment': renderAppointment,
	'home-listing': renderListing,
	'shopping-product': renderShoppingProduct,
	'electronics-component': renderElectronicsComponent,
	'nutrition-recipe': renderNutritionRecipe,
	'weather-day': renderWeatherDay,
	'social-media-post': renderSocialMediaPost,
	'focus-mode-activation': (c) => {
		const name = str(c.focus_mode_name) ?? '';
		return `**Focus Mode**${name ? ` — ${name}` : ''}`;
	}
};

// ── Public API ───────────────────────────────────────────────────────────

/**
 * Render decoded embed content as human-readable plain text.
 *
 * @param registryKey - Registry key (e.g. "app:web:search" or "web-website")
 * @param content - Decoded TOON content
 * @param children - Optional resolved child embed contents for composite embeds
 * @returns Human-readable text, or a fallback label if no renderer found
 */
export function renderEmbedAsText(
	registryKey: string,
	content: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const renderer = EMBED_TEXT_RENDERERS[registryKey];
	if (renderer) {
		return renderer(content, children);
	}

	// Generic fallback: show first few non-internal fields
	const lines: string[] = [`[${registryKey}]`];
	let count = 0;
	for (const [k, v] of Object.entries(content)) {
		if (count >= 3) break;
		if (v !== null && v !== undefined && typeof v !== 'object' && !k.startsWith('_')) {
			lines.push(`${k}: ${trunc(String(v), 80)}`);
			count++;
		}
	}
	return lines.join('\n');
}
