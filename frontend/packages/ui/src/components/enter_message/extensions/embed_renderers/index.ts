// Embed renderer registry - handles all embed types including groups
//
// Auto-populated from the generated EMBED_RENDERER_MAP (sourced from app.yml embed_types).
// To add a new embed type renderer, add an embed_types entry to the relevant app.yml
// and rebuild — do NOT add manual entries to this file.
//
// Architecture: docs/architecture/embeds.md

import { GroupRenderer } from "./GroupRenderer";
import { ImageRenderer } from "./ImageRenderer";
import { PdfRenderer } from "./PdfRenderer";
import { RecordingRenderer } from "./RecordingRenderer";
import { AppSkillUseRenderer } from "./AppSkillUseRenderer";
import { FocusModeActivationRenderer } from "./FocusModeActivationRenderer";
import { MapLocationRenderer } from "./MapLocationRenderer";
import { MathPlotRenderer } from "./MathPlotRenderer";
import type { EmbedRenderer, EmbedRendererRegistry } from "./types";
import { EMBED_RENDERER_MAP } from "../../../../data/embedRegistry.generated";

/**
 * Map from renderer class identifier (string in generated registry) to actual renderer instance.
 * Renderer classes are instantiated once and shared across all embed types that use them.
 */
const rendererInstances: Record<string, EmbedRenderer> = {
  GroupRenderer: new GroupRenderer(),
  AppSkillUseRenderer: new AppSkillUseRenderer(),
  FocusModeActivationRenderer: new FocusModeActivationRenderer(),
  ImageRenderer: new ImageRenderer(),
  PdfRenderer: new PdfRenderer(),
  RecordingRenderer: new RecordingRenderer(),
  MapLocationRenderer: new MapLocationRenderer(),
  MathPlotRenderer: new MathPlotRenderer(),
};

/**
 * Registry of all embed renderers, built from the auto-generated EMBED_RENDERER_MAP.
 * Each entry maps a frontend embed type string to its renderer instance.
 */
export const embedRenderers: EmbedRendererRegistry = Object.fromEntries(
  Object.entries(EMBED_RENDERER_MAP)
    .map(([embedType, rendererName]) => {
      const instance = rendererInstances[rendererName];
      if (!instance) {
        console.warn(
          `[embed-renderers] Unknown renderer "${rendererName}" for type "${embedType}"`,
        );
        return null;
      }
      return [embedType, instance];
    })
    .filter((entry): entry is [string, EmbedRenderer] => entry !== null),
);

/**
 * Get renderer for a specific embed type
 * @param embedType - The embed type (e.g., 'web-website', 'app-skill-use-group')
 * @returns The renderer instance or null if not found
 */
export function getEmbedRenderer(embedType: string) {
  return embedRenderers[embedType] || null;
}
