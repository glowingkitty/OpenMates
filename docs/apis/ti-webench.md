# TI WEBENCH Integration Summary

## Overview

OpenMates uses TI WEBENCH Power Designer to find power converter reference
designs from electrical requirements such as input voltage, output voltage,
output current, isolation, ambient temperature, and optimization goal.

This integration is reverse-engineered from `https://webench.ti.com/power-designer/`.
It is not an official public API, so it should be monitored and re-tested
regularly.

## Authentication

- Type: none observed
- Vault key name: none
- API key required: no

## Endpoints Used

### Search Power Solutions

- URL: `POST https://webench.ti.com/wb6/restapi/power/solutions`
- Purpose: Return ranked power converter reference designs matching requirements.

### Schematic Preview

- URL: `GET https://webench.ti.com/wb6/restapi/power/solutions/{solution_id}/schsvg`
- Purpose: Return an SVG schematic preview for a selected solution.
- Header requirement: send `Content-Type: application/json` even for GET.

### BOM Components

- URL: `GET https://webench.ti.com/wb6/restapi/power/solutions/{solution_id}/bomcomponents`
- Purpose: Return BOM parts, quantities, values, manufacturers, and component limits.
- Header requirement: send `Content-Type: application/json` even for GET.

## Input Structure

| Parameter | Type | Required | Description |
|---|---|---|---|
| `vinMin` | number | yes | Minimum input voltage in volts |
| `vinMax` | number | yes | Maximum input voltage in volts |
| `vout` | number[] | yes | Output voltage rails in volts; first skill supports one rail |
| `iout` | number[] | yes | Output current rails in amps; first skill supports one rail |
| `ambientTemp` | number | no | Ambient temperature in deg C, default 30 |
| `isIsolated` | boolean | no | Whether isolated conversion is required |
| `powerSupply` | string | no | `dc` or `ac` |
| `optimizationSetting` | integer | no | 1 small footprint, 2 low cost, 3 balanced, 4 high efficiency |

## Output Structure

| Field | Type | Description |
|---|---|---|
| `id` | string | WEBENCH solution ID used for schematic/BOM follow-ups |
| `rank` | integer | Provider ranking |
| `considerations` | string | Human-readable design description |
| `info.device.partNumber` | string | Specific TI orderable part number |
| `info.device.basePn` | string | TI base product page identifier |
| `info.device.topology` | string | Converter topology |
| `info.bomCost` | number | Estimated BOM cost in USD |
| `info.efficiency` | number | Efficiency as 0-1 ratio |
| `info.footprint` | number | Footprint in mm2 |
| `info.frequency` | number | Switching frequency in Hz |
| `info.temperature` | number | Estimated operating temperature in deg C |

## Pricing

- Free tier: public web endpoint, no pricing published
- Paid tier: not applicable
- Estimated cost: no direct API cost observed; use conservative rate limiting

## Limitations

- Reverse-engineered endpoint, no stability guarantee.
- TI can change schema, headers, rate limits, or access requirements.
- Results are reference-design candidates, not complete PCB layouts.
- Schematic SVG is visual plus metadata, not a formal EDA netlist.
- Deeper customize/simulation/export endpoints are under `/secured` and require WEBENCH login tokens.

## Scaling Considerations

- Cache repeated searches by normalized requirement payload.
- Keep result counts low for chat use (`max_results <= 20`).
- Monitor 4xx/5xx rates and schema validation failures.
- Re-test monthly because this is not an official public API.

## Reverse-Engineered Integration Warning

This integration is not based on official TI API documentation. It was derived
from the public WEBENCH Power Designer Angular bundle and verified with live
requests on 2026-05-23. Treat provider responses as best-effort external data
and show component links back to `ti.com` for source verification.
