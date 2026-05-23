/**
 * Preview mock data for ElectronicsComponentEmbedFullscreen.
 * Provides a direct component prop for child-detail fullscreen rendering.
 * Access path: /dev/preview/embeds/electronics.
 * Architecture context: docs/architecture/embeds.md.
 */

const defaultProps = {
  component: {
    embed_id: "preview-electronics-component-fs-1",
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
    output_ripple_vpp: 0.014,
    input_voltage_min_v: 4.5,
    input_voltage_max_v: 17,
    output_voltage_min_v: 0.6,
    output_voltage_max_v: 7,
    isolated: false,
  },
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  alternate: {
    component: {
      ...defaultProps.component,
      embed_id: "preview-electronics-component-fs-2",
      part_number: "TPS563257DRLR",
      base_part_number: "TPS563257",
      product_url: "https://www.ti.com/product/TPS563257",
      datasheet_url: "https://www.ti.com/lit/gpn/tps563257",
      efficiency_percent: 91.8,
      bom_cost_usd: 0.43,
      footprint_mm2: 84.2,
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
