import { modelsMetadata } from '../../data/modelsMetadata';

const model = modelsMetadata.find(candidate => candidate.id === 'claude-fable-5-1');
const includedModel = modelsMetadata.find(candidate => candidate.id === 'gpt-6.1-sol');
if (!model?.default_server || !model.pricing?.cache_read_tokens_per_credit || !model.pricing.cache_write_tokens_per_credit) {
  throw new Error('Cache pricing preview model is missing proposed rates');
}
if (!includedModel?.default_server || !includedModel.pricing?.cache_read_tokens_per_credit) {
  throw new Error('Included-write cache pricing preview model is missing proposed rates');
}

export default { modelId: model.id };

// Synthetic policy variants exercise inactive/expired states independently of
// the live catalog. Catalog variants use the published rates without overrides.
export const variants = {
  'catalog-google': { modelId: 'gemini-3.8-flash' },
  'catalog-openai': { modelId: 'gpt-6.1-sol' },
  'catalog-anthropic': { modelId: 'claude-sonnet-5-5' },
  'catalog-haiku': { modelId: 'claude-haiku-5-5' },
  'catalog-mistral': { modelId: 'mistral-small-latest' },
  'cache-active': {
    modelOverride: {
      ...model,
      pricing: { ...model.pricing },
      cache_pricing: {
        ...model.cache_pricing,
        enabled: true,
        status: 'verified_for_activation',
        reviewed_on: '2026-10-06',
        expires_on: '2099-12-31',
        eligible_hosts: [model.default_server],
        cache_write_1h_hosts: [model.default_server],
        write_billing: 'separate' as const,
      },
    },
  },
  'cache-expired': {
    modelOverride: {
      ...model,
      pricing: { ...model.pricing },
      cache_pricing: {
        ...model.cache_pricing,
        enabled: true,
        status: 'verified_for_activation',
        reviewed_on: '2026-10-06',
        expires_on: '2026-10-06',
        eligible_hosts: [model.default_server],
      },
    },
  },
  'cache-active-included': {
    modelId: includedModel.id,
    modelOverride: {
      ...includedModel,
      pricing: { ...includedModel.pricing },
      cache_pricing: {
        ...includedModel.cache_pricing,
        enabled: true,
        status: 'verified_for_activation',
        reviewed_on: '2026-10-06',
        expires_on: '2099-12-31',
        eligible_hosts: [includedModel.default_server],
        write_billing: 'included_in_input' as const,
      },
    },
  },
};
