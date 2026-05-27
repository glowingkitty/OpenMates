/**
 * Preview mock data for ElectronicsSearchEmbedPreview.
 * Provides TI WEBENCH-style component search results for the app embed showcase.
 * Access path: /dev/preview/embeds/electronics.
 * Architecture context: docs/architecture/embeds.md.
 */

const sampleResults = [
  {
    type: "power_converter",
    provider: "TI WEBENCH",
    part_number: "TPS564257DRLR",
    base_part_number: "TPS564257",
    title: "TPS564257DRLR Buck converter",
    topology: "Buck",
    package: "SOT-563",
    regulator_type: "Converter",
    product_url: "https://www.ti.com/product/TPS564257",
    datasheet_url: "https://www.ti.com/lit/gpn/tps564257",
    bom_cost_usd: 0.47,
    bom_count: 11,
    efficiency_percent: 92.4,
    footprint_mm2: 89.6,
  },
  {
    type: "power_converter",
    provider: "TI WEBENCH",
    part_number: "TPS563257DRLR",
    base_part_number: "TPS563257",
    title: "TPS563257DRLR Buck converter",
    topology: "Buck",
    package: "SOT-563",
    regulator_type: "Converter",
    product_url: "https://www.ti.com/product/TPS563257",
    datasheet_url: "https://www.ti.com/lit/gpn/tps563257",
    bom_cost_usd: 0.43,
    bom_count: 10,
    efficiency_percent: 91.8,
    footprint_mm2: 84.2,
  },
];

const defaultProps = {
  id: "preview-electronics-search-1",
  query: "12V to 3.3V buck converter at 3A",
  provider: "TI WEBENCH",
  status: "finished" as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: {
    id: "preview-electronics-search-processing",
    query: "24V to 5V isolated converter",
    provider: "TI WEBENCH",
    status: "processing" as const,
    results: [],
    isMobile: false,
  },
  error: {
    id: "preview-electronics-search-error",
    query: "invalid converter search",
    provider: "TI WEBENCH",
    status: "error" as const,
    results: [],
    isMobile: false,
  },
  mobile: {
    ...defaultProps,
    id: "preview-electronics-search-mobile",
    isMobile: true,
  },
};
