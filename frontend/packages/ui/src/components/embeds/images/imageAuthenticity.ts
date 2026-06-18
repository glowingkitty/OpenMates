// frontend/packages/ui/src/components/embeds/images/imageAuthenticity.ts
// Shared view-model helpers for uploaded image authenticity badges.
// Keeps Sightengine threshold, provider attribution, and percentage copy
// consistent across preview and fullscreen image embed components.
// Tests cover the user-facing labels without mounting Svelte components.

export interface AIDetectionMetadata {
  ai_generated: number;
  provider: string;
  status?: 'success' | 'failed';
  error?: string | null;
}

export type ImageAuthenticityStatus = 'ai_generated' | 'authentic' | 'failed';

export interface ImageAuthenticityBadgeViewModel {
  status: ImageAuthenticityStatus;
  probabilityLabel: string;
  providerLabel: string;
  providerUrl: string | null;
  explanationLabel: string;
  ariaLabel: string;
}

type TranslateFunction = (key: string, vars?: Record<string, unknown>) => string;

export const AI_GENERATED_THRESHOLD = 0.7;
export const AUTHENTIC_THRESHOLD = 0.4;
export const SIGHTENGINE_URL = 'https://sightengine.com/';

export function clampAIGeneratedScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  if (score < 0) return 0;
  if (score > 1) return 1;
  return score;
}

export function getImageAuthenticityStatus(
  aiDetection: AIDetectionMetadata | null | undefined,
): ImageAuthenticityStatus | null {
  if (!aiDetection) return null;
  if (aiDetection.status === 'failed') return 'failed';
  const score = clampAIGeneratedScore(aiDetection.ai_generated);
  if (score > AI_GENERATED_THRESHOLD) return 'ai_generated';
  if (score <= AUTHENTIC_THRESHOLD) return 'authentic';
  return null;
}

export function formatAIGeneratedPercentage(score: number): string {
  return `${Math.round(clampAIGeneratedScore(score) * 100)}%`;
}

export function getDetectionProviderLabel(provider: string | null | undefined): string {
  if (!provider) return 'Sightengine';
  return provider.toLowerCase() === 'sightengine' ? 'Sightengine' : provider;
}

export function getDetectionProviderUrl(provider: string | null | undefined): string | null {
  return !provider || provider.toLowerCase() === 'sightengine' ? SIGHTENGINE_URL : null;
}

export function buildAuthenticityBadgeViewModel(
  aiDetection: AIDetectionMetadata | null | undefined,
  translate: TranslateFunction,
): ImageAuthenticityBadgeViewModel | null {
  const status = getImageAuthenticityStatus(aiDetection);
  if (!status || !aiDetection) return null;

  const percentage = formatAIGeneratedPercentage(aiDetection.ai_generated);
  const probabilityLabel = translate('app_skills.images.view.ai_generated_chance', { percentage });
  const providerLabel = getDetectionProviderLabel(aiDetection.provider);
  const providerUrl = getDetectionProviderUrl(aiDetection.provider);
  const statusLabel = translate(
    status === 'failed'
      ? 'app_skills.images.view.detection_failed_title'
      : status === 'ai_generated'
      ? 'app_skills.images.view.ai_generated'
      : 'app_skills.images.view.authentic',
  );
  const viaProvider = translate('app_skills.images.view.via_provider', { provider: providerLabel });
  const explanationLabel = translate(
    status === 'failed'
      ? 'app_skills.images.view.detection_failed_description'
      : 'app_skills.images.view.detection_limitations',
  );

  return {
    status,
    probabilityLabel: status === 'failed'
      ? translate('app_skills.images.view.detection_failed_retry')
      : probabilityLabel,
    providerLabel,
    providerUrl,
    explanationLabel,
    ariaLabel: `${statusLabel}. ${status === 'failed' ? translate('app_skills.images.view.detection_failed_retry') : probabilityLabel}. ${viaProvider}. ${explanationLabel}`,
  };
}
