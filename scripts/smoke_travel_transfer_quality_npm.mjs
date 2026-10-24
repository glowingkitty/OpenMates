#!/usr/bin/env node
/** Offline saved-travel contract validation. No SDK, credentials or runtime is contacted. */
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const SECRET_LEAK_MARKERS = ["SECRET__GEOAPIFY", "apiKey", "api_key", "access_token", "Authorization"];

function extractData(payload) {
  return payload && typeof payload.data === "object" && payload.data !== null ? payload.data : payload;
}

function resultGroups(data) {
  if (!Array.isArray(data?.results)) throw new Error(`Travel SDK response did not include result groups: ${JSON.stringify(data).slice(0, 900)}`);
  return data.results.filter((group) => group && typeof group === "object");
}

function layovers(result) {
  const out = [];
  for (const leg of Array.isArray(result.legs) ? result.legs : []) {
    for (const layover of Array.isArray(leg?.layovers) ? leg.layovers : []) {
      if (layover && typeof layover === "object") out.push(layover);
    }
  }
  return out;
}

export function validateTravelContract(payload, minTransferMinutes) {
  const serialized = JSON.stringify(payload);
  const leaked = SECRET_LEAK_MARKERS.filter((marker) => serialized.includes(marker));
  if (leaked.length > 0) throw new Error(`Travel response leaked forbidden provider/auth markers: ${leaked.join(", ")}`);
  const data = extractData(payload);
  const groups = resultGroups(data);
  const firstGroup = groups[0];
  const results = Array.isArray(firstGroup?.results) ? firstGroup.results : null;
  if (!results) throw new Error(`Travel SDK response group missing results: ${JSON.stringify(firstGroup).slice(0, 900)}`);
  if (results.length === 0) {
    const reason = firstGroup.no_result_reason || firstGroup.error;
    if (typeof reason !== "string" || !reason) throw new Error("Empty travel SDK response must explain no results");
    return { status: "passed", mode: "empty_with_reason", reason, result_count: 0, provider: data.provider };
  }
  let transferQualityResults = 0;
  let optimizedCount = 0;
  let amenityLayoverCount = 0;
  let layoverCount = 0;
  for (const result of results) {
    if (!result || typeof result !== "object") continue;
    if (result.transfer_quality && typeof result.transfer_quality === "object") {
      if (result.transfer_quality.min_transfer_minutes !== minTransferMinutes) throw new Error(`Unexpected min transfer metadata: ${JSON.stringify(result.transfer_quality)}`);
      transferQualityResults += 1;
    }
    if (result.optimization?.optimized_by === "openmates") {
      if (result.optimization.badge !== "Optimized by OpenMates") throw new Error(`Optimized result missing badge: ${JSON.stringify(result.optimization)}`);
      optimizedCount += 1;
    }
    for (const layover of layovers(result)) {
      layoverCount += 1;
      if (Number.isInteger(layover.duration_minutes) && layover.duration_minutes < minTransferMinutes) throw new Error(`Result includes too-short transfer after filtering: ${JSON.stringify(layover)}`);
      if (layover.amenities && typeof layover.amenities === "object") {
        const groupsValue = layover.amenities.groups;
        for (const key of ["food_drink", "shops", "toilets"]) {
          if (!groupsValue || typeof groupsValue !== "object" || !(key in groupsValue)) throw new Error(`Transfer amenities missing ${key}: ${JSON.stringify(layover.amenities)}`);
        }
        amenityLayoverCount += 1;
      }
    }
  }
  if (transferQualityResults === 0) throw new Error("Travel SDK results did not include transfer_quality metadata");
  return {
    status: "passed",
    mode: "results",
    provider: data.provider,
    result_count: results.length,
    transfer_quality_results: transferQualityResults,
    layover_count: layoverCount,
    amenity_layover_count: amenityLayoverCount,
    optimized_count: optimizedCount,
  };
}

export function runSdkSmoke(args) {
  if (!args.fixture) return {
    status: "skipped", mode: "capability_unavailable", surface: "npm",
    reason: "Connection discovery has no permitted provider. Live smoke is unavailable.",
    runtime_target: null, network_requests: 0,
  };
  return {
    ...validateTravelContract(JSON.parse(readFileSync(args.fixture, "utf8")), args.minTransferMinutes),
    execution: "offline_saved_fixture", surface: "npm", runtime_target: null, network_requests: 0,
  };
}

function main(argv) {
  const args = { minTransferMinutes: 15, json: false };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--fixture") args.fixture = argv[++index];
    else if (flag === "--min-transfer-minutes") args.minTransferMinutes = Number(argv[++index]);
    else if (flag === "--json") args.json = true;
    else if (["--api", "--api-key", "--device-id", "--scenario"].includes(flag)) index += 1;
    else if (["--create-api-key-from-cli-session", "--skip-build"].includes(flag)) continue;
    else if (["--help", "-h"].includes(flag)) {
      console.log("Offline saved-travel validation: --fixture response.json --min-transfer-minutes 15 --json. Without a fixture, live smoke is explicitly skipped.");
      return;
    } else throw new Error(`Unknown argument: ${flag}`);
  }
  const summary = runSdkSmoke(args);
  console.log(args.json ? JSON.stringify(summary, null, 2) : `Travel contract ${summary.status}: ${summary.reason || summary.mode}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { main(process.argv.slice(2)); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
}
