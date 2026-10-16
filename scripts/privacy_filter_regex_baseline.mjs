// Evaluate the actual Project-file detector with synthetic fixtures only.
import fs from "node:fs";
import { performance } from "node:perf_hooks";
import { detectPII } from "../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts";

const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"), (_key, value) =>
  value && !Array.isArray(value) && typeof value === "object" &&
  Object.keys(value).length === 1 && Array.isArray(value.synthetic_parts)
    ? value.synthetic_parts.join("") : value);
const rows = cases.map((fixture) => {
  const start = performance.now();
  let matches;
  for (let i = 0; i < 5; i++) matches = detectPII(fixture.text);
  const spans = (values) => values.map((value) => ({
    label: value.type,
    // OpenMates uses UTF-16 offsets; the Python evaluator uses code points.
    start: Array.from(fixture.text.slice(0, value.startIndex)).length,
    end: Array.from(fixture.text.slice(0, value.endIndex)).length,
    text: value.match,
  }));
  return {
    id: fixture.id,
    seconds: (performance.now() - start) / 5000,
    spans: spans(matches),
    configured_spans: fixture.custom ? spans(detectPII(fixture.text, {
      personalDataEntries: fixture.custom.map((text, index) => ({
        textToHide: text, replaceWith: `CUSTOM_${index}`,
      })),
    })) : undefined,
  };
});
process.stdout.write(JSON.stringify(rows));
