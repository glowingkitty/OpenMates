import { parse } from "yaml";

export interface PricingTier {
  credits: number;
  price: {
    eur: number;
    usd?: number; // Optional — bank-transfer-only tiers are EUR-only (SEPA)
  };
  label?: string; // Optional - will be generated dynamically
  monthly_auto_top_up_extra_credits?: number;
  recommended?: boolean; // Optional - marks the recommended pricing tier
  bank_transfer_only?: boolean; // If true, this tier is only available via SEPA bank transfer (EUR only)
}

// Load shared pricing configuration
let pricingData: Record<string, PricingTier[]> = { pricingTiers: [] };

// Try to load the shared YAML file
try {
  const yamlModule = import.meta.glob("/../../../shared/config/pricing.yml", {
    eager: true,
    query: "?raw",
    import: "default",
  });
  const yamlPath = Object.keys(yamlModule)[0];
  if (yamlPath) {
    const yamlContent = yamlModule[yamlPath] as string;
    pricingData = parse(yamlContent);
  } else {
    console.error("No YAML file found at expected path");
  }
} catch (error) {
  console.error("Failed to load shared pricing configuration:", error);
}

// Parse the YAML data - no fallback, fail if not loaded
export const pricingTiers: PricingTier[] = pricingData.pricingTiers || [];

/**
 * Generate a human-readable label for a pricing tier
 * @param credits - Number of credits
 * @returns Formatted label string (e.g., "21.000 credits")
 */
export const generateCreditsLabel = (credits: number): string => {
  // Format with dots as thousands separators (European style)
  return `${credits.toLocaleString("de-DE")} credits`;
};

/**
 * Get pricing tiers with generated labels for frontend display
 * @returns Array of pricing tiers with generated labels
 */
const _getPricingTiersWithLabels = (): PricingTier[] => {
  return pricingTiers.map((tier) => ({
    ...tier,
    label: generateCreditsLabel(tier.credits), // Always generate labels dynamically
  }));
};

/**
 * Get pricing tiers formatted for the signup component
 * @param currency - Currency to use for pricing
 * @returns Array of pricing tiers formatted for CreditsBottomContent
 */
export const getPricingTiersForSignup = (currency: "eur" | "usd" = "eur") => {
  return pricingTiers
    .filter((tier) => !tier.bank_transfer_only) // Exclude bank-transfer-only tiers from signup
    .filter((tier) => tier.price[currency] !== undefined) // Skip tiers missing the requested currency
    .map((tier) => ({
      credits_amount: tier.credits,
      price: tier.price[currency] as number,
      currency: currency.toUpperCase(),
      recommended: tier.recommended || false, // Use recommended flag from YAML configuration
      label: generateCreditsLabel(tier.credits), // Always generate labels dynamically
    }));
};

/**
 * Get all pricing tiers including bank-transfer-only tiers, for settings billing.
 * Tiers without a price for the requested currency (e.g. SEPA-only tiers in USD)
 * are filtered out.
 * @param currency - Currency to use for pricing
 * @returns Array of pricing tiers formatted for settings
 */
export const getPricingTiersForSettings = (currency: "eur" | "usd" = "eur") => {
  return pricingTiers
    .filter((tier) => tier.price[currency] !== undefined)
    .map((tier) => ({
      credits_amount: tier.credits,
      price: tier.price[currency] as number,
      currency: currency.toUpperCase(),
      recommended: tier.recommended || false,
      label: generateCreditsLabel(tier.credits),
      bank_transfer_only: tier.bank_transfer_only || false,
    }));
};

const _getCreditsByPrice = (
  price: number,
  currency: "eur" | "usd",
): number | undefined => {
  const tier = pricingTiers.find((tier) => tier.price[currency] === price);
  return tier?.credits;
};

const _getPriceByCredits = (
  credits: number,
  currency: "eur" | "usd",
): number | undefined => {
  const tier = pricingTiers.find((tier) => tier.credits === credits);
  return tier?.price[currency];
};
