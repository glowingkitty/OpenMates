/**
 * Preview mock data for ElectronicsSearchEmbedFullscreen.
 * Uses legacy flat props that the dev preview wrapper converts to data.decodedContent.
 * Access path: /dev/preview/embeds/electronics.
 * Architecture context: docs/architecture/embeds.md.
 */

const sampleResults = [
  {
    embed_id: "preview-electronics-component-1",
    provider: "TI WEBENCH",
    part_number: "TPS564257DRLR",
    base_part_number: "TPS564257",
    title: "TPS564257DRLR Buck converter",
    topology: "Buck",
    package: "SOT-563",
    regulator_type: "Converter",
    control_mode: "D-CAP3",
    product_url: "https://www.ti.com/product/TPS564257",
    datasheet_url: "https://www.ti.com/lit/gpn/tps564257",
    description: "Compact synchronous buck converter reference design from TI WEBENCH.",
    bom_cost_usd: 0.47,
    bom_count: 11,
    efficiency_percent: 92.4,
    footprint_mm2: 89.6,
    frequency_hz: 650000,
    max_output_current_a: 4,
    input_voltage_min_v: 4.5,
    input_voltage_max_v: 17,
    output_voltage_min_v: 0.6,
    output_voltage_max_v: 7,
    isolated: false,
  },
  {
    embed_id: "preview-electronics-component-2",
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
    isolated: false,
  },
];

const defaultProps = {
  query: "12V to 3.3V buck converter at 3A",
  provider: "TI WEBENCH",
  status: "finished" as const,
  results: sampleResults,
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  processing: {
    query: "24V to 5V isolated converter",
    provider: "TI WEBENCH",
    status: "processing" as const,
    results: [],
    onClose: () => {},
  },
  error: {
    query: "invalid converter search",
    provider: "TI WEBENCH",
    status: "error" as const,
    results: [],
    onClose: () => {},
  },
};
