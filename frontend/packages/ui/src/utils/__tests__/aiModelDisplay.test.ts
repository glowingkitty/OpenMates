// frontend/packages/ui/src/utils/__tests__/aiModelDisplay.test.ts
// Guards the Figma-defined AI provider branding and ordering contract.
// Also verifies the deterministic capability scale derived from model metadata.

import { describe, expect, it, vi } from 'vitest';

import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
import {
    compareAiModels,
    compareAiProviders,
    getAiProviderDisplay,
    getModelCapabilityLevel,
    getRecommendedModelForTier,
    isEligibleLegacyAiModel,
    splitAiProviderModels,
} from '../aiModelDisplay';
import { isAiModelSelectionUsable } from '../aiModelSelection';

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
    // contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
    it('shows only recent, unretired Claude and OpenAI legacy chat models', () => {
        const today = new Date('2026-10-08T12:00:00Z');
        const recent = { ...model('anthropic', 'Claude', 'high', '2026-05-28'),
            for_app_skill: 'ai.ask', servers: [{ id: 'anthropic', name: 'Anthropic', region: 'US' as const }],
            legacy_model: true };
        const main = { ...recent, id: 'main', legacy_model: false };
        expect(isEligibleLegacyAiModel(recent, today)).toBe(true);
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2025-10-07' }, today)).toBe(false);
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2025-10-08' }, today)).toBe(true);
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2026-10-09' }, today)).toBe(false);
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2026-02-30' }, today)).toBe(false);
        expect(isEligibleLegacyAiModel({ ...recent, api_retirement_date: '2026-10-08' }, today)).toBe(false);
        expect(isEligibleLegacyAiModel({ ...recent, api_retirement_date: '2026-10-09' }, today)).toBe(true);
        expect(isEligibleLegacyAiModel({ ...recent, provider_id: 'google' }, today)).toBe(false);
        expect(isEligibleLegacyAiModel({ ...recent, for_app_skill: 'images.generate' }, today)).toBe(false);
        const leapDay = new Date('2028-02-29T12:00:00Z');
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2027-02-28' }, leapDay)).toBe(true);
        expect(isEligibleLegacyAiModel({ ...recent, release_date: '2027-02-27' }, leapDay)).toBe(false);
        expect(splitAiProviderModels([main, recent], today)).toEqual({ main: [main], old: [recent] });
    });

    // contract-test: supporting surface=gui.web assertions=ai-model-routing.unavailable.notify-reset-auto
    it('rejects an expired or retired saved legacy selection', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-10-08T12:00:00Z'));
        try {
            const legacy: AIModelMetadata = {
                ...model('anthropic', 'Claude', 'high', '2026-05-28'),
                id: 'claude-opus-4-8', for_app_skill: 'ai.ask', legacy_model: true,
                servers: [{ id: 'anthropic', name: 'Anthropic', region: 'US' }],
            };
            const usable = (candidate: AIModelMetadata) => isAiModelSelectionUsable(
                'anthropic/claude-opus-4-8', {}, () => true, [candidate],
            );
            expect(usable(legacy)).toBe(true);
            expect(usable({ ...legacy, release_date: '2025-10-07' })).toBe(false);
            expect(usable({ ...legacy, api_retirement_date: '2026-10-08' })).toBe(false);
        } finally {
            vi.useRealTimers();
        }
    });
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
