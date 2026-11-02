//! Inactive Worker binding foundation. No native session import/export, cookies,
//! raw-key RPC, or application policy. Admission is exclusively the shared SDK.
#![forbid(unsafe_code)]

#[cfg(target_arch = "wasm32")]
mod browser;
#[cfg(target_arch = "wasm32")]
pub use browser::*;

#[cfg(target_arch = "wasm32")]
mod browser_crypto;

#[cfg(all(test, target_arch = "wasm32"))]
mod legacy_password_test_context;

#[cfg(all(test, target_arch = "wasm32"))]
mod browser_socket_close_tests;
