import pricingYaml from '../../../../../shared/config/pricing.yml';

export interface PricingTier {
  credits: number;
  price: {
    eur: number;
    usd: number;
    jpy: number;
  };
  label?: string;
}

// Parse the YAML data
export const pricingTiers: PricingTier[] = pricingYaml.pricingTiers;

export const getCreditsByPrice = (price: number, currency: 'eur' | 'usd' | 'jpy'): number | undefined => {
  const tier = pricingTiers.find(tier => tier.price[currency] === price);
  return tier?.credits;
};

export const getPriceByCredits = (credits: number, currency: 'eur' | 'usd' | 'jpy'): number | undefined => {
  const tier = pricingTiers.find(tier => tier.credits === credits);
  return tier?.price[currency];
};
