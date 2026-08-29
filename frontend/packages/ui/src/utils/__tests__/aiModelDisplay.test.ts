// frontend/packages/ui/src/utils/__tests__/aiModelDisplay.test.ts
// Guards the Figma-defined AI provider branding and ordering contract.
// Also verifies the deterministic capability scale derived from model metadata.

import { describe, expect, it } from 'vitest';

import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
import {
    compareAiModels,
    compareAiProviders,
    getAiProviderDisplay,
    getModelCapabilityLevel,
    getRecommendedModelForTier,
} from '../aiModelDisplay';

function model(
    providerId: string,
    providerName: string,
    capabilityLevel: NonNullable<AIModelMetadata['capability_level']>,
    releaseDate = '2026-01-01',
): AIModelMetadata {
    return {
        id: `${providerId}-model`,
        name: `${providerName} model`,
        description: '',
        provider_id: providerId,
        provider_name: providerName,
        logo_svg: '',
        country_origin: 'US',
        input_types: ['text'],
        output_types: ['text'],
        tier: 'standard',
        capability_level: capabilityLevel,
        release_date: releaseDate,
    };
}

describe('AI model settings display contract', () => {
    // contract-test: direct surface=gui.web assertions=ai-model-routing.settings.hierarchy-canonical
    it('uses consumer-facing product brands with company attribution', () => {
        expect(getAiProviderDisplay('openai', 'OpenAI')).toMatchObject({ brandName: 'ChatGPT', companyName: 'OpenAI' });
        expect(getAiProviderDisplay('anthropic', 'Anthropic')).toMatchObject({ brandName: 'Claude', companyName: 'Anthropic' });
        expect(getAiProviderDisplay('google', 'Google')).toMatchObject({ brandName: 'Gemini', companyName: 'Google' });
        expect(getAiProviderDisplay('mistral', 'Mistral')).toMatchObject({ brandName: 'Mistral', companyName: 'Mistral' });
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.settings.hierarchy-canonical
    it('orders providers like the approved AI settings design', () => {
        const providers = [
            model('alibaba', 'Alibaba', 'medium'),
            model('google', 'Google', 'medium'),
            model('deepseek', 'DeepSeek', 'medium'),
            model('mistral', 'Mistral', 'medium'),
            model('anthropic', 'Anthropic', 'medium'),
            model('openai', 'OpenAI', 'medium'),
        ].sort(compareAiProviders);

        expect(providers.map((provider) => provider.provider_id)).toEqual([
            'openai', 'anthropic', 'mistral', 'deepseek', 'google', 'alibaba',
        ]);
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('uses explicit low, medium, high, and max model capabilities', () => {
        expect(getModelCapabilityLevel(model('a', 'A', 'low'))).toBe('low');
        expect(getModelCapabilityLevel(model('b', 'B', 'medium'))).toBe('medium');
        expect(getModelCapabilityLevel(model('c', 'C', 'high'))).toBe('high');
        expect(getModelCapabilityLevel(model('d', 'D', 'max'))).toBe('max');
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('includes explicit capabilities in generated AI model metadata', () => {
        const aiModels = modelsMetadata.filter((candidate) => candidate.for_app_skill === 'ai.ask');
        expect(aiModels.length).toBeGreaterThan(0);
        expect(aiModels.filter((candidate) => !candidate.capability_level).map((candidate) => candidate.id)).toEqual([]);
    });

    // contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('sorts models by newest release, then highest capability, then stable id', () => {
        const models = [
            model('old-max', 'Old max', 'max', '2025-12-01'),
            model('new-low', 'New low', 'low', '2026-01-01'),
            model('new-max-b', 'New max B', 'max', '2026-01-01'),
            model('new-max-a', 'New max A', 'max', '2026-01-01'),
        ].sort(compareAiModels);

        expect(models.map((candidate) => candidate.provider_id)).toEqual([
            'new-max-a', 'new-max-b', 'new-low', 'old-max',
        ]);
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('recommends the closest eligible capability for each request tier', () => {
        const candidates = [
            model('economy', 'Economy', 'low'),
            model('standard', 'Standard', 'medium'),
            model('premium', 'Premium', 'high'),
            model('reasoning', 'Reasoning', 'max'),
        ];

        expect(getRecommendedModelForTier(candidates, 'simple')?.provider_id).toBe('economy');
        expect(getRecommendedModelForTier(candidates, 'complex')?.provider_id).toBe('premium');
        expect(getRecommendedModelForTier(candidates, 'most-demanding')?.provider_id).toBe('reasoning');
    });
});
