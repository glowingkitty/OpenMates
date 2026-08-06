/**
 * Offline OCR bridge for specification demonstration privacy scans.
 * It reads one PPM/PNG/JPEG image from stdin and writes recognized text only.
 * The worker, WASM core, and English traineddata resolve from local packages;
 * no image or model data is sent over the network.
 * Architecture: docs/specs/narrated-spec-demonstration-videos/spec.yml.
 */

import englishData from "@tesseract.js-data/eng";
import { createWorker } from "tesseract.js";


const chunks = [];
for await (const chunk of process.stdin) {
  chunks.push(chunk);
}
const image = Buffer.concat(chunks);
if (image.length === 0) {
  throw new Error("OCR input image is empty");
}

const worker = await createWorker("eng", undefined, {
  langPath: englishData.langPath,
  gzip: englishData.gzip,
  cacheMethod: "readOnly",
  logger: () => {},
});
try {
  const result = await worker.recognize(image);
  process.stdout.write(result.data.text);
} finally {
  await worker.terminate();
}
