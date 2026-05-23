/**
 * Preview mock data for ElectronicsComponentEmbedPreview.
 * Shows one TI WEBENCH component/reference-design child card.
 * Access path: /dev/preview/embeds/electronics.
 * Architecture context: docs/architecture/embeds.md.
 */

const defaultProps = {
  id: "preview-electronics-component-1",
  provider: "TI WEBENCH",
  part_number: "TPS564257DRLR",
  base_part_number: "TPS564257",
  title: "TPS564257DRLR Buck converter",
  topology: "Buck",
  package: "SOT-563",
  regulator_type: "Converter",
  bom_cost_usd: 0.47,
  bom_count: 11,
  efficiency_percent: 92.4,
  footprint_mm2: 89.6,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  compact: {
    ...defaultProps,
    id: "preview-electronics-component-compact",
    part_number: "TPS563257DRLR",
    efficiency_percent: 91.8,
    bom_cost_usd: 0.43,
    footprint_mm2: 84.2,
  },
  mobile: {
    ...defaultProps,
    id: "preview-electronics-component-mobile",
    isMobile: true,
  },
};
