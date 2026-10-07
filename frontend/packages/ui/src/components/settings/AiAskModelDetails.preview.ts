import { modelsMetadata } from '../../data/modelsMetadata';

const model = modelsMetadata.find(candidate => candidate.id === 'claude-fable-5');
const includedModel = modelsMetadata.find(candidate => candidate.id === 'gpt-6.1-sol');
if (!model?.default_server || !model.pricing?.cache_read_tokens_per_credit || !model.pricing.cache_write_tokens_per_credit) {
  throw new Error('Cache pricing preview model is missing proposed rates');
}
if (!includedModel?.default_server || !includedModel.pricing?.cache_read_tokens_per_credit) {
  throw new Error('Included-write cache pricing preview model is missing proposed rates');
}

export default { modelId: model.id };

// The variant copies the catalog entry. Preview routing merges this prop only
// for ?variant=cache-active; the shared catalog remains disabled.
export const variants = {
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
