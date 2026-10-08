import { modelsMetadata } from '../../data/modelsMetadata';

const model = modelsMetadata.find(candidate => candidate.id === 'gpt-6.1-sol');
const haiku = modelsMetadata.find(candidate => candidate.id === 'claude-haiku-5-5');
if (!model?.default_server || !model.pricing?.context_bands?.over_272k) {
  throw new Error('Long-context pricing preview model is missing catalog rates');
}
if (!haiku?.default_server || !haiku.pricing?.context_bands?.over_100k) {
  throw new Error('Haiku pricing preview model is missing catalog rates');
}

const base = { appId: 'ai', skillId: 'ask', modelId: model.id };
export default base;

export const variants = {
  'catalog-haiku': { appId: 'ai', skillId: 'ask', modelId: haiku.id },
  'long-context-active': {
    ...base,
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
        write_billing: 'included_in_input' as const,
      },
    },
  },
  'long-context-inactive': {
    ...base,
    modelOverride: {
      ...model,
      cache_pricing: { ...model.cache_pricing, enabled: false },
    },
  },
};
