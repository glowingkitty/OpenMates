// frontend/packages/ui/src/data/embedRegistry.generated.d.ts
// Type declarations for the gitignored generated embedRegistry.generated.ts module.
// The runtime file is produced by frontend/packages/ui/scripts/generate-embed-registry.js
// during UI prepare/prebuild steps, but changed-file TypeScript checks can run
// before generated artifacts exist in a clean worktree.

export const EMBED_TYPE_NORMALIZATION_MAP: Record<string, string>;
export const EMBED_CHILD_TYPE_MAP: Record<string, string>;
export const EMBED_PREVIEW_COMPONENTS: Record<string, string>;
export const EMBED_FULLSCREEN_COMPONENTS: Record<string, string>;
export const EMBED_RENDERER_MAP: Record<string, string>;

export interface EmbedTypeMetadata {
  icon?: string;
  gradientVar?: string;
  i18nNamespace?: string;
  appId?: string;
  skillId?: string;
  hasChildren?: boolean;
  childFrontendType?: string;
}

export const EMBED_METADATA: Record<string, EmbedTypeMetadata>;

export interface ContentEmbedCatalogItem {
  id: string;
  appId: string;
  contentTypeId: string;
  registryKey: string;
  frontendType: string;
  backendType?: string;
  skillId?: string;
  name: string;
  description: string;
  icon?: string;
  gradientVar?: string;
  i18nNamespace?: string;
  exampleKey: string;
  order: number;
  source: string;
}

export const CONTENT_EMBED_CATALOG: ContentEmbedCatalogItem[];
export const EMBED_GROUPABLE_TYPES: string[];

export function normalizeEmbedType(backendType: string): string;
export function getChildEmbedType(appId: string, skillId: string): string;
export function isGroupableType(frontendType: string): boolean;
