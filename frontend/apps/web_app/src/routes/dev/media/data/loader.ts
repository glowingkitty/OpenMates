/**
 * YAML-based scenario loader for media generation templates.
 *
 * Loads chat scenarios, template configs, and brand assets from YAML files
 * stored alongside the media routes. Uses Vite's import.meta.glob for
 * automatic discovery of all .yml files.
 *
 * Usage:
 *   const scenario = await loadScenario('cuttlefish-chat');
 *   const config = await loadTemplateConfig('og-github');
 *
 * Architecture: docs/media-generation.md
 */

import { parse as parseYaml } from 'yaml';
import type { MediaScenario, MediaTemplateConfig } from './types';

// Vite glob import: discovers all YAML files in the scenarios/ and templates/ dirs
// at build time. The ?raw suffix imports them as plain strings.
const scenarioModules = import.meta.glob('../scenarios/*.yml', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const templateModules = import.meta.glob('../templates/*/*.yml', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

/**
 * Parse and return a scenario YAML by its ID (filename without extension).
 * Example: loadScenario('cuttlefish-chat') loads ../scenarios/cuttlefish-chat.yml
 */
export function loadScenario(id: string): MediaScenario {
	const key = Object.keys(scenarioModules).find(k => k.includes(`/${id}.yml`));
	if (!key) {
		throw new Error(`Scenario not found: ${id}. Available: ${Object.keys(scenarioModules).map(k => k.split('/').pop()?.replace('.yml', '')).join(', ')}`);
	}
	const raw = scenarioModules[key];
	const parsed = parseYaml(raw) as MediaScenario;
	parsed.id = id;
	return parsed;
}

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
 * List all available scenario IDs.
 */
export function listScenarios(): string[] {
	return Object.keys(scenarioModules).map(k => {
		const filename = k.split('/').pop() || '';
		return filename.replace('.yml', '');
	});
}

/**
 * List all available template IDs.
 */
export function listTemplates(): string[] {
	return [...new Set(
		Object.keys(templateModules).map(k => k.split('/').at(-2)).filter(Boolean) as string[]
	)];
}
