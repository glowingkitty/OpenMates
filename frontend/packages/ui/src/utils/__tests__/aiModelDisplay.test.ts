// frontend/packages/ui/src/utils/__tests__/aiModelDisplay.test.ts
// Guards the Figma-defined AI provider branding and ordering contract.
// Also verifies the deterministic capability scale derived from model metadata.

import { describe, expect, it } from 'vitest';

import type { AIModelMetadata } from '../../data/modelsMetadata';
import {
    compareAiProviders,
    getAiProviderDisplay,
    getModelCapabilityLevel,
    getRecommendedModelForTier,
} from '../aiModelDisplay';

function model(providerId: string, providerName: string, tier: AIModelMetadata['tier'], reasoning = false): AIModelMetadata {
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
        tier,
        reasoning,
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
            model('alibaba', 'Alibaba', 'standard'),
            model('google', 'Google', 'standard'),
            model('deepseek', 'DeepSeek', 'standard'),
            model('mistral', 'Mistral', 'standard'),
            model('anthropic', 'Anthropic', 'standard'),
            model('openai', 'OpenAI', 'standard'),
        ].sort(compareAiProviders);

        expect(providers.map((provider) => provider.provider_id)).toEqual([
            'openai', 'anthropic', 'mistral', 'deepseek', 'google', 'alibaba',
        ]);
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('maps model tiers to the low, medium, high, and max scale', () => {
        expect(getModelCapabilityLevel(model('a', 'A', 'economy'))).toBe('low');
        expect(getModelCapabilityLevel(model('b', 'B', 'standard'))).toBe('medium');
        expect(getModelCapabilityLevel(model('c', 'C', 'premium'))).toBe('high');
        expect(getModelCapabilityLevel(model('d', 'D', 'premium', true))).toBe('max');
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('recommends the closest eligible capability for each request tier', () => {
        const candidates = [
            model('economy', 'Economy', 'economy'),
            model('standard', 'Standard', 'standard'),
            model('premium', 'Premium', 'premium'),
            model('reasoning', 'Reasoning', 'premium', true),
        ];

        expect(getRecommendedModelForTier(candidates, 'simple')?.provider_id).toBe('economy');
        expect(getRecommendedModelForTier(candidates, 'complex')?.provider_id).toBe('premium');
        expect(getRecommendedModelForTier(candidates, 'most-demanding')?.provider_id).toBe('reasoning');
    });
});
