/**
 * Data-driven embed fullscreen resolver service.
 *
 * Uses embedRegistry.generated.ts to dynamically resolve and load fullscreen
 * components by registry key. Replaces the ~940-line if/else chain in ActiveChat
 * with a ~30-line svelte:component block.
 *
 * Architecture: docs/architecture/frontend/data-driven-embed-fullscreen-routing.md
 */

import type { Component } from 'svelte';
import {
	EMBED_FULLSCREEN_COMPONENTS,
	normalizeEmbedType
} from '../data/embedRegistry.generated';

/**
 * Resolve an embed type + decoded content to a registry key.
 *
 * Applies the generated normalizeEmbedType first so both server types
 * ("website", "code") and frontend types ("web-website", "code-code")
 * resolve to the correct registry key.
 *
 * For app-skill-use embeds, combines app_id + skill_id into "app:{appId}:{skillId}".
 * For direct types (recording, pdf, etc.), returns the normalized frontend type.
 *
 * @returns Registry key string, or null if unresolvable
 */
export function resolveRegistryKey(
	embedType: string,
	decodedContent?: Record<string, unknown>
): string | null {
	const normalized = normalizeEmbedType(embedType);

	if (normalized === 'app-skill-use') {
		const appId = decodedContent?.app_id;
		const skillId = decodedContent?.skill_id;
		if (typeof appId === 'string' && typeof skillId === 'string') {
			return `app:${appId}:${skillId}`;
		}
		return null;
	}
	return normalized;
}

/**
 * Check if the registry has a fullscreen component for a given key.
 */
export function hasFullscreenComponent(key: string): boolean {
	return key in EMBED_FULLSCREEN_COMPONENTS;
}

/**
 * Vite glob import for all fullscreen embed components.
 * Lazy-loaded: each module is only fetched when its path is requested.
 */
const modules = import.meta.glob<{ default: Component }>(
	'../components/embeds/**/*EmbedFullscreen.svelte'
);

/**
 * Dynamically load a fullscreen component by registry key.
 *
 * Uses Vite's import.meta.glob for code-splitting — each component is
 * loaded on demand, not bundled upfront.
 *
 * @returns The Svelte component constructor, or null if not found
 */
export async function loadFullscreenComponent(
	key: string
): Promise<Component | null> {
	const path = EMBED_FULLSCREEN_COMPONENTS[key];
	if (!path) return null;

	const importPath = `../components/embeds/${path}`;
	const loader = modules[importPath];
	if (!loader) {
		console.error(
			`[embedFullscreenResolver] No module loader for key="${key}", path="${importPath}". ` +
				`Available modules: ${Object.keys(modules).length}`
		);
		return null;
	}

	const module = await loader();
	return module.default;
}
