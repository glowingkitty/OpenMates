/** Shared web and terminal chat category colors and icon names. */
export const CATEGORY_GRADIENTS: Record<
  string,
  { start: string; end: string }
> = {
  software_development: { start: "#155D91", end: "#42ABF4" },
  business_development: { start: "#004040", end: "#008080" },
  medical_health: { start: "#FD50A0", end: "#F42C2D" },
  legal_law: { start: "#239CFF", end: "#005BA5" }, // Legacy - kept for backwards compatibility
  openmates_official: { start: "#6366f1", end: "#4f46e5" }, // Official OpenMates brand colors (indigo)
  maker_prototyping: { start: "#EA7600", end: "#FBAB59" },
  marketing_sales: { start: "#FF8C00", end: "#F4B400" },
  finance: { start: "#119106", end: "#15780D" },
  design: { start: "#101010", end: "#2E2E2E" },
  electrical_engineering: { start: "#233888", end: "#2E4EC8" },
  movies_tv: { start: "#00C2C5", end: "#3170DC" },
  history: { start: "#4989F2", end: "#2F44BF" },
  science: { start: "#CE5B06", end: "#8F220E" },
  life_coach_psychology: { start: "#FDB250", end: "#F42C2D" },
  cooking_food: { start: "#FD8450", end: "#F42C2D" },
  activism: { start: "#F53D00", end: "#F56200" },
  general_knowledge: { start: "#DE1E66", end: "#FF763B" },
  onboarding_support: { start: "#6364FF", end: "#9B6DFF" }, // Suki's purple gradient (matches matesMetadata.ts)
};

/**
 * Fallback icons for categories
 */
export const CATEGORY_FALLBACK_ICONS: Record<string, string> = {
  software_development: "code",
  business_development: "briefcase",
  medical_health: "heart",
  legal_law: "gavel", // Legacy - kept for backwards compatibility
  openmates_official: "shield-check", // Official category uses shield icon
  maker_prototyping: "wrench",
  marketing_sales: "megaphone",
  finance: "dollar-sign",
  design: "palette",
  electrical_engineering: "zap",
  movies_tv: "tv",
  history: "clock",
  science: "microscope",
  life_coach_psychology: "users",
  cooking_food: "utensils",
  activism: "trending-up",
  general_knowledge: "help-circle",
  onboarding_support: "compass", // Suki's compass icon (matches matesMetadata.ts)
};

