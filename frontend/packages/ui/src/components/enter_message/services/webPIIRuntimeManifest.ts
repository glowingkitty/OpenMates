/** Reviewed public release bytes. Never derive these pins from downloaded files.
 * SDK npm gitHead: 86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb.
 * HF public, ungated v0.4.0 API checked 2026-10-28: revision below; model and
 * tokenizer SHA-256/size match its LFS metadata; labels SHA-256 also matches
 * the reviewed native benchmark copy (Git blob fe76679736d86b47a45fe03a94994aa292fc6203).
 */
export const piiRuntimeVersion = 'redact-4.1.0-litert-2.6.0';
export const piiRuntimeBase = `/pii-runtime/${piiRuntimeVersion}/`;
export const piiModel = Object.freeze({
  repository: 'desert-ant-labs/redact', version: 'v0.4.0',
  revision: '3ed5033aeb544f454ebde77dc76fd7b7e76cc572',
});
export const piiPinnedFiles = Object.freeze({
  'sdk.js': { bytes: 112953, sha256: 'df634631a5e13292bd7d346f31a8a3329dd3e30a295fd215b46c9a51a7f030bf' },
  'RedactWeb.wasm': { bytes: 46278336, sha256: '84689a2378bbff7a8a8f5ba7790c5765173aa9b4ff38e2578999b8051dc8eea4' },
  'litert_wasm_compat_internal.js': { bytes: 279036, sha256: 'cffb7bebb9411e2160d711ccff00c3921b0031a66a692f58c25ce8204b7ec541' },
  'litert_wasm_compat_internal.wasm': { bytes: 10948854, sha256: '4190033238e53ec86b832bad4649851ad111025c226c1688cfae20e1f8fe8926' },
  'model/redact.tflite': { bytes: 24529472, sha256: 'ee36727f07e3237569e71427bfe661463a82e526f7e97e92b0fa583cad16ed27' },
  'model/redact_tokenizer.bin': { bytes: 391416, sha256: '81bc354dc99285e05b8f70edca9df3afbd83dfa4b0cea18d0448ab17ce58aae2' },
  'model/labels.json': { bytes: 3842, sha256: '228835734235f85ec4bf31391a296aa6e8a36684e1171e841ac94f7b3f9b430a' },
});
