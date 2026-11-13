// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright specs are CommonJS. */
/**
 * Flag-on (VITE_OPENMATES_RUST_CORE=1) run of message-highlights.spec.ts. CI builds the Rust
 * core web app only for specs named web-rust-core-*, so this wrapper registers the
 * unchanged flows of the product spec in that lane: the highlight payload encryption,
 * the update/remove frames and the inbound decode then run on the shared Worker chatState
 * unit instead of the TypeScript services.
 */
export {};

require('./message-highlights.spec.ts');
