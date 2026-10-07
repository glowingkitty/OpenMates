import { modelsMetadata } from '../../data/modelsMetadata';

const model = modelsMetadata.find(candidate => candidate.id === 'gpt-6.1-sol');
if (!model?.default_server || !model.pricing?.context_bands?.over_272k) {
  throw new Error('Long-context pricing preview model is missing catalog rates');
}

const base = { appId: 'ai', skillId: 'ask', modelId: model.id };
export default base;

export const variants = {
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
  'long-context-inactive': base,
};
