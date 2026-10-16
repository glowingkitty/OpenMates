/** Public customer tariffs only. Supplier costs never enter this schedule. */
export interface TemporaryPriceMetadata {
  id: string;
  effective_from: string;
  expires_on?: string;
  guaranteed_through?: string;
  source_url: string;
  reviewed_on: string;
  eligible_hosts: string[];
  processing_tier: string;
  regions?: string[];
}
export interface PublicTemporaryPrice<P> extends TemporaryPriceMetadata { pricing: P }
export interface ScheduledModel<P> {
  pricing?: P;
  default_server?: string;
  servers?: Array<{ id: string; region: string }>;
  temporary_prices?: PublicTemporaryPrice<P>[];
  active_temporary_price?: TemporaryPriceMetadata;
}
function validDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export function resolveTemporaryModelPrice<P>(model: ScheduledModel<P>, today = new Date().toISOString().slice(0, 10)) {
  const region = model.servers?.find(server => server.id === model.default_server)?.region;
  const candidates = model.temporary_prices?.filter(price => {
    const rates = price.pricing as Record<string, unknown>;
    const base = model.pricing as Record<string, unknown> | undefined;
    const tokenKeys = Object.keys(base ?? {}).filter(key => key.endsWith('_tokens_per_credit'));
    if (!rates || !base || !tokenKeys.length ||
        Object.keys(rates).filter(key => key.endsWith('_tokens_per_credit')).sort().join() !== tokenKeys.sort().join() ||
        !tokenKeys.every(key => typeof rates[key] === 'number' && Number.isFinite(rates[key]) && (rates[key] as number) > 0)) return false;
    return Boolean(price.id && /^https:\/\//.test(price.source_url) && validDate(price.effective_from) && validDate(price.reviewed_on) &&
      price.effective_from <= today && price.reviewed_on <= today &&
      (!price.expires_on || (validDate(price.expires_on) && price.expires_on >= today && price.expires_on >= price.effective_from)) &&
      (!price.guaranteed_through || (validDate(price.guaranteed_through) && price.guaranteed_through >= price.effective_from && (!price.expires_on || price.guaranteed_through <= price.expires_on))) &&
      price.processing_tier === 'standard' && Array.isArray(price.eligible_hosts) && price.eligible_hosts.includes(model.default_server ?? '') &&
      (!price.regions || (Array.isArray(price.regions) && price.regions.length && Boolean(region && price.regions.includes(region)))));
  });
  // Overlapping applicable offers cannot authorize a guessed discount.
  const active = candidates?.length === 1 ? candidates[0] : undefined;
  if (!active) return { pricing: model.pricing, active_temporary_price: undefined };
  const { pricing, ...metadata } = active;
  return { pricing, active_temporary_price: metadata };
}
/** Getters keep every existing catalog read current even in a long-lived tab. */
export function bindTemporaryModelPricing<P, M extends ScheduledModel<P>>(model: M): M & ScheduledModel<P> {
  const regularPricing = model.pricing;
  const source = { ...model, pricing: regularPricing };
  Object.defineProperties(model, {
    pricing: { enumerable: true, get: () => resolveTemporaryModelPrice(source).pricing },
    active_temporary_price: { enumerable: true, get: () => resolveTemporaryModelPrice(source).active_temporary_price },
  });
  return model;
}
