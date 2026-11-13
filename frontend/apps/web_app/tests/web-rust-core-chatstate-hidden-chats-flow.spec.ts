// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright specs are CommonJS. */
/**
 * Flag-on (VITE_OPENMATES_RUST_CORE=1) run of hidden-chats-flow.spec.ts. CI builds the Rust
 * core web app only for specs named web-rust-core-*, so this wrapper registers the
 * unchanged flows of the product spec in that lane: hide/unhide/fork decisions then
 * run on the shared Worker chatState unit instead of the TypeScript services.
 */
export {};

require('./hidden-chats-flow.spec.ts');
