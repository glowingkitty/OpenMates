import {
  CONTENT_EMBED_CATALOG,
  EMBED_PREVIEW_COMPONENT_PRESENTATION,
  normalizeEmbedType,
} from '../data/embedRegistry.generated';

export type EmbedPreviewPresentation = 'content' | 'execution';
export type EmbedPreviewPresentationContext = EmbedPreviewPresentation | { readonly presentation: EmbedPreviewPresentation };
export const EMBED_PREVIEW_PRESENTATION_CONTEXT = Symbol('embed-preview-presentation');

const durableRoutes = new Set(CONTENT_EMBED_CATALOG
  .filter(item => item.source === 'self')
  .map(item => item.registryKey));

/** Actual output type takes precedence over a colliding parent skill route. */
export function getEmbedPreviewPresentation(actualType?: string, registryKey?: string): EmbedPreviewPresentation {
  const actual = normalizeEmbedType(actualType?.trim() ?? '');
  const route = registryKey?.trim() ?? '';
  if (actual && actual !== 'app-skill-use' && !actual.startsWith('app:')) return 'content';
  const executionRoute = route.startsWith('app:') ? route : actual.startsWith('app:') ? actual : '';
  // Registry wildcard fallbacks (e.g. legacy code) are content adapters, not
  // a concrete executed skill. Explicit execution types still take precedence.
  if (!actual && executionRoute.endsWith(':*')) return 'content';
  if (durableRoutes.has(executionRoute)) return 'content';
  return actual === 'app-skill-use' || executionRoute ? 'execution' : 'content';
}

/** Component paths are emitted by the registry generator, never inferred from filenames. */
export function getComponentPreviewPresentation(componentPath: string): EmbedPreviewPresentation {
  let path = componentPath.replace(/^\/?dev\/preview\//, '').replace(/^\//, '').replace(/^embeds\//, '');
  if (!path.endsWith('.svelte')) path += '.svelte';
  return EMBED_PREVIEW_COMPONENT_PRESENTATION[path] ?? 'content';
}
