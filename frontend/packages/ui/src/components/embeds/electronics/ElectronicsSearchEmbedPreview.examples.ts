/**
 * App-store examples for the electronics/search_components skill.
 *
 * Uses real TI WEBENCH provider results captured from live skill runs. The
 * parent search embeds keep nested `results` arrays so the preview and
 * fullscreen exercise the same legacy-result path as normal skill output.
 */

export interface ElectronicsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: ElectronicsSearchStoreExample[] = [
  {
    "id": "store-example-electronics-search-components-1",
    "query": "12V to 5V buck converter",
    "query_translation_key": "settings.app_store_examples.electronics.search_components.1",
    "provider": "TI WEBENCH",
    "status": "finished",
    "results": [{
      "id": 1,
      "results": [
        {
          "type": "power_converter",
          "provider": "TI WEBENCH",
          "part_number": "TPS563209DDCR",
          "base_part_number": "TPS563209",
          "title": "TPS563209DDCR Buck",
          "description": "17V, 3A,6-pin, Low Iq Synchronous buck converter with Advanced Eco-mode",
          "product_url": "https://www.ti.com/product/TPS563209",
          "datasheet_url": "https://www.ti.com/lit/gpn/tps563209",
          "topology": "Buck",
          "package": "SOT-23-THIN",
          "regulator_type": "INTEGRATEDFET",
          "control_mode": "D-CAP2",
          "price_usd": 0.342,
          "bom_cost_usd": 0.96,
          "bom_count": 9,
          "efficiency_percent": 94.74,
          "footprint_mm2": 166,
          "frequency_hz": 795088.326323947,
          "temperature_c": 59.521335508604494,
          "max_output_current_a": 3,
          "output_ripple_vpp": 0.008653692617532446,
          "input_voltage_min_v": 4.5,
          "input_voltage_max_v": 17,
          "output_voltage_min_v": 0.77,
          "output_voltage_max_v": 7,
          "isolated": false
        },
        {
          "type": "power_converter",
          "provider": "TI WEBENCH",
          "part_number": "TPS563200DDCR",
          "base_part_number": "TPS563200",
          "title": "TPS563200DDCR Buck",
          "description": "17V, 3A,6-pin, Low Iq Synchronous buck converter with Advanced Eco-mode",
          "product_url": "https://www.ti.com/product/TPS563200",
          "datasheet_url": "https://www.ti.com/lit/gpn/tps563200",
          "topology": "Buck",
          "package": "SOT-23-THIN",
          "regulator_type": "INTEGRATEDFET",
          "control_mode": "D-CAP2",
          "price_usd": 0.359,
          "bom_cost_usd": 0.98,
          "bom_count": 9,
          "efficiency_percent": 94.74,
          "footprint_mm2": 166,
          "frequency_hz": 795088.326323947,
          "temperature_c": 59.521335508604494,
          "max_output_current_a": 3,
          "output_ripple_vpp": 0.008653692617532446,
          "input_voltage_min_v": 4.5,
          "input_voltage_max_v": 17,
          "output_voltage_min_v": 0.77,
          "output_voltage_max_v": 7,
          "isolated": false
        },
        {
          "type": "power_converter",
          "provider": "TI WEBENCH",
          "part_number": "TPS562242DRLR",
          "base_part_number": "TPS562242",
          "title": "TPS562242DRLR Buck",
          "description": "3-V to 16-V Input, 2-A Synchronous Step-Down Voltage Regulator",
          "product_url": "https://www.ti.com/product/TPS562242",
          "datasheet_url": "https://www.ti.com/lit/gpn/tps562242",
          "topology": "Buck",
          "package": "SOT-5X3",
          "regulator_type": "INTEGRATEDFET",
          "control_mode": "D-CAP3",
          "price_usd": 0.173,
          "bom_cost_usd": 0.64,
          "bom_count": 13,
          "efficiency_percent": 95.43,
          "footprint_mm2": 169,
          "frequency_hz": 1301719.7147161025,
          "temperature_c": 59.2630520329342,
          "max_output_current_a": 2,
          "output_ripple_vpp": 0.006515870466045225,
          "input_voltage_min_v": 3,
          "input_voltage_max_v": 17,
          "output_voltage_min_v": 0.8,
          "output_voltage_max_v": 10,
          "isolated": false
        }
      ]
    }]
  },
  {
    "id": "store-example-electronics-search-components-2",
    "query": "24V to 3.3V regulator module",
    "query_translation_key": "settings.app_store_examples.electronics.search_components.2",
    "provider": "TI WEBENCH",
    "status": "finished",
    "results": [{
      "id": 1,
      "results": [
        {
          "type": "power_converter",
          "provider": "TI WEBENCH",
          "part_number": "LMZM23601V3SILR",
          "base_part_number": "LMZM23601V3",
          "title": "LMZM23601V3SILR Buck",
          "description": "LMZM23601 36-V 1-A Step-Down DC-DC Nano Module",
          "product_url": "https://www.ti.com/product/LMZM23601V3",
          "datasheet_url": "https://www.ti.com/lit/gpn/lmzm23601v3",
          "topology": "Buck",
          "package": "uSiP",
          "regulator_type": "MODULE",
          "control_mode": "Peak Current Mode",
          "price_usd": 2.906,
          "bom_cost_usd": 3.37,
          "bom_count": 5,
          "efficiency_percent": 74.59,
          "footprint_mm2": 46,
          "frequency_hz": 750000,
          "temperature_c": 72.70128811737267,
          "max_output_current_a": 1,
          "output_ripple_vpp": 0.003013533822196604,
          "input_voltage_min_v": 4,
          "input_voltage_max_v": 36,
          "output_voltage_min_v": 3.3,
          "output_voltage_max_v": 3.3,
          "isolated": false
        },
        {
          "type": "power_converter",
          "provider": "TI WEBENCH",
          "part_number": "LMR36015BRNXR",
          "base_part_number": "LMR36015B",
          "title": "LMR36015BRNXR Buck",
          "description": "This regulator is an easy to use synchronous step-down DC-DC converter capable of driving up to 1.5A",
          "product_url": "https://www.ti.com/product/LMR36015B",
          "datasheet_url": "https://www.ti.com/lit/gpn/lmr36015b",
          "topology": "Buck",
          "package": "VQFN-HR",
          "regulator_type": "INTEGRATEDFET",
          "control_mode": "Peak Current Mode",
          "price_usd": 1.155,
          "bom_cost_usd": 2.36,
          "bom_count": 11,
          "efficiency_percent": 80.62,
          "footprint_mm2": 83,
          "frequency_hz": 1000000,
          "temperature_c": 76.1665825227983,
          "max_output_current_a": 1.5,
          "output_ripple_vpp": 0.002325622998232736,
          "input_voltage_min_v": 4.2,
          "input_voltage_max_v": 60,
          "output_voltage_min_v": 1,
          "output_voltage_max_v": 28,
          "isolated": false
        }
      ]
    }]
  }
];

export default examples;
