/**
 * YAML config loader for media generation templates.
 *
 * Loads template configs from YAML files stored alongside the media routes.
 * Uses Vite's import.meta.glob for automatic discovery of all .yml files.
 *
 * Device screens now load the real app via iframes (?media=1), so the old
 * YAML scenario system (cuttlefish-chat, etc.) has been removed. Chat content
 * comes from the live app and the media test account.
 *
 * Usage:
 *   const config = loadTemplateConfig('og-github');
 *
 * Architecture: docs/media-generation.md
 */

import { parse as parseYaml } from 'yaml';
import type { MediaTemplateConfig } from './types';

// Vite glob import: discovers all YAML files in templates/ at build time.
// The ?raw suffix imports them as plain strings.
const templateModules = import.meta.glob('../templates/*/*.yml', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

/**
 * Parse and return a template config YAML.
 * Example: loadTemplateConfig('og-github') looks for ../templates/og-github/*.yml
 */
export function loadTemplateConfig(templateId: string): MediaTemplateConfig {
	const key = Object.keys(templateModules).find(k => k.includes(`/${templateId}/`));
	if (!key) {
		throw new Error(`Template config not found: ${templateId}. Available: ${Object.keys(templateModules).map(k => k.split('/').at(-2)).filter(Boolean).join(', ')}`);
	}
	const raw = templateModules[key];
	return parseYaml(raw) as MediaTemplateConfig;
}

/**
 * List all available template IDs.
 */
export function listTemplates(): string[] {
	return [...new Set(
		Object.keys(templateModules).map(k => k.split('/').at(-2)).filter(Boolean) as string[]
	)];
}
