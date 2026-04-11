/**
 * App-store skill examples resolver.
 *
 * Loads real, curated embed example fixtures (`*Preview.examples.ts`) alongside
 * their preview + fullscreen Svelte components, so the settings app store can
 * render rich "Examples" sections under each skill. The examples themselves are
 * captured from real skill runs (see backend/scripts/run_app_skill_request.py)
 * and live next to the preview components they drive.
 *
 * Resolution: `app:${appId}:${skillId}` → paths from the generated embed
 * registry → dynamic import via Vite's import.meta.glob.
 */
import type { Component } from 'svelte';
import {
  EMBED_PREVIEW_COMPONENTS,
  EMBED_FULLSCREEN_COMPONENTS,
} from '../data/embedRegistry.generated';

const previewComponentModules = import.meta.glob<{ default: Component }>(
  '../components/embeds/**/*EmbedPreview.svelte'
);

const fullscreenComponentModules = import.meta.glob<{ default: Component }>(
  '../components/embeds/**/*EmbedFullscreen.svelte'
);

const exampleModules = import.meta.glob<{
  default: Array<Record<string, unknown>>;
}>('../components/embeds/**/*EmbedPreview.examples.ts');

function registryKey(appId: string, skillId: string): string {
  return `app:${appId}:${skillId}`;
}

export function hasSkillExamples(appId: string, skillId: string): boolean {
  const key = registryKey(appId, skillId);
  const previewPath = EMBED_PREVIEW_COMPONENTS[key];
  if (!previewPath) return false;
  const examplesPath = `../components/embeds/${previewPath.replace(
    'Preview.svelte',
    'Preview.examples.ts'
  )}`;
  return examplesPath in exampleModules;
}

export interface SkillExamplesBundle {
  previewComponent: Component;
  fullscreenComponent: Component | null;
  examples: Array<Record<string, unknown>>;
}

export async function loadSkillExamples(
  appId: string,
  skillId: string
): Promise<SkillExamplesBundle | null> {
  const key = registryKey(appId, skillId);
  const previewPath = EMBED_PREVIEW_COMPONENTS[key];
  if (!previewPath) return null;

  const previewImportPath = `../components/embeds/${previewPath}`;
  const examplesImportPath = `../components/embeds/${previewPath.replace(
    'Preview.svelte',
    'Preview.examples.ts'
  )}`;

  const previewLoader = previewComponentModules[previewImportPath];
  const examplesLoader = exampleModules[examplesImportPath];
  if (!previewLoader || !examplesLoader) return null;

  const fullscreenPath = EMBED_FULLSCREEN_COMPONENTS[key];
  const fullscreenLoader = fullscreenPath
    ? fullscreenComponentModules[`../components/embeds/${fullscreenPath}`]
    : undefined;

  const [previewMod, examplesMod, fullscreenMod] = await Promise.all([
    previewLoader(),
    examplesLoader(),
    fullscreenLoader ? fullscreenLoader() : Promise.resolve(null),
  ]);

  return {
    previewComponent: previewMod.default,
    fullscreenComponent:
      (fullscreenMod as { default?: Component } | null)?.default ?? null,
    examples: examplesMod.default ?? [],
  };
}
