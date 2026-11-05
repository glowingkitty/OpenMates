// Shared source-owned pins are also compiled into the trusted host broker.
export { piiRuntimeVersion, piiRuntimeBase, piiModel, piiPinnedFiles } from '../../../packages/ui/src/components/enter_message/services/webPIIRuntimeManifest.ts';

export const piiRegistryIntegrities = Object.freeze({
  '@desert-ant-labs/core@4.1.0': 'sha512-o5QUCmKKyM+HWaiv5FhuknsNEON2/x7z3gp8c8gybR5eKPWvTVzAibb8fln0j1wrZFFDeINL/CRHc+6xm+MHSw==',
  '@desert-ant-labs/redact@4.1.0': 'sha512-6OoLYmVpWiCscvlr45e6mqafgaG6ueCUAEcnXFLnNrJwugye/+rUgso4OQy8JtJXDkqe2a3pAe9BubXIb4yQ2w==',
  '@litertjs/core@2.6.0': 'sha512-TH6/5zLq57YzyZH6q+vO8be1SvTH76uDFe+CiL0wWtRNTUDhc2GAWm2YCohhnyt4fPvefSNztg5PKFZGAYL0cw==',
});

// A Worker response has its own CSP; the page CSP does not seal its fetches.
// Only verified, host-delivered Blob scripts and WASM compilation are allowed.
export const piiWorkerCSP = "default-src 'none'; connect-src 'none'; script-src blob: 'wasm-unsafe-eval'; worker-src 'none'; child-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
