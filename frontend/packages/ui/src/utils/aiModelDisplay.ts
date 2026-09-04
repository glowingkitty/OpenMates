/**
 * Shared display rules for AI model settings.
 * Keeps provider product names, company attribution, ordering, and
 * capability labels consistent across overview and detail pages.
 * Product routing continues to use provider and model IDs.
 */

import type { AIModelMetadata } from '../data/modelsMetadata';

export type AiCapabilityLevel = 'low' | 'medium' | 'high' | 'max';
type AiRequestTier = 'simple' | 'complex' | 'most-demanding';

interface ProviderDisplay {
    brandName: string;
    companyName: string;
    order: number;
}

const PROVIDER_DISPLAY: Record<string, ProviderDisplay> = {
    openai: { brandName: 'ChatGPT', companyName: 'OpenAI', order: 0 },
    anthropic: { brandName: 'Claude', companyName: 'Anthropic', order: 1 },
    mistral: { brandName: 'Mistral', companyName: 'Mistral', order: 2 },
    deepseek: { brandName: 'DeepSeek', companyName: 'DeepSeek', order: 3 },
    google: { brandName: 'Gemini', companyName: 'Google', order: 4 },
    alibaba: { brandName: 'Qwen', companyName: 'Alibaba', order: 5 },
    moonshot: { brandName: 'Kimi', companyName: 'Moonshot AI', order: 6 },
    zai: { brandName: 'GLM', companyName: 'Z.ai', order: 7 },
};

export function getAiProviderDisplay(providerId: string, fallbackName: string): ProviderDisplay {
    return PROVIDER_DISPLAY[providerId] ?? {
        brandName: fallbackName,
        companyName: fallbackName,
        order: Number.MAX_SAFE_INTEGER,
    };
}

export function compareAiProviders(a: AIModelMetadata, b: AIModelMetadata): number {
    const aDisplay = getAiProviderDisplay(a.provider_id, a.provider_name);
    const bDisplay = getAiProviderDisplay(b.provider_id, b.provider_name);
    return aDisplay.order - bDisplay.order || aDisplay.brandName.localeCompare(bDisplay.brandName);
}

export function getModelCapabilityLevel(model: AIModelMetadata): AiCapabilityLevel {
    if (!model.capability_level) {
        throw new Error(`Missing capability_level for AI model ${model.id}`);
    }
    return model.capability_level;
}

export function compareAiModels(a: AIModelMetadata, b: AIModelMetadata): number {
    if (!a.release_date || !b.release_date) {
        throw new Error(`Missing release_date for AI model ${!a.release_date ? a.id : b.id}`);
    }
    const capabilityRank: Record<AiCapabilityLevel, number> = { low: 0, medium: 1, high: 2, max: 3 };
    return b.release_date.localeCompare(a.release_date)
        || capabilityRank[getModelCapabilityLevel(b)] - capabilityRank[getModelCapabilityLevel(a)]
        || a.id.localeCompare(b.id);
}

export function getTierCapabilityLevel(tier: AiRequestTier): AiCapabilityLevel {
    if (tier === 'simple') return 'low';
    if (tier === 'complex') return 'high';
    return 'max';
}

export function getRecommendedModelForTier(
    models: AIModelMetadata[],
    tier: AiRequestTier,
): AIModelMetadata | null {
    const rank: Record<AiCapabilityLevel, number> = { low: 0, medium: 1, high: 2, max: 3 };
    const targetRank = rank[getTierCapabilityLevel(tier)];
    return [...models].sort((a, b) => {
        const capabilityDistance = Math.abs(rank[getModelCapabilityLevel(a)] - targetRank)
            - Math.abs(rank[getModelCapabilityLevel(b)] - targetRank);
        return capabilityDistance || a.id.localeCompare(b.id);
    })[0] ?? null;
}
