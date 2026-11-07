//! Inactive Worker binding foundation. No native session import/export, cookies,
//! raw-key RPC, or application policy. Admission is exclusively the shared SDK.
#![forbid(unsafe_code)]

#[cfg(target_arch = "wasm32")]
mod browser;
#[cfg(target_arch = "wasm32")]
pub use browser::*;

#[cfg(target_arch = "wasm32")]
mod browser_crypto;
#[cfg(target_arch = "wasm32")] pub mod browser_search_pii;
#[cfg(target_arch = "wasm32")] pub mod browser_apps;
#[cfg(target_arch = "wasm32")] pub mod browser_parse;
#[cfg(target_arch = "wasm32")] pub mod browser_transfer;
#[cfg(target_arch = "wasm32")] pub mod browser_keys;
#[cfg(target_arch = "wasm32")] pub mod browser_send_prep;
#[cfg(target_arch = "wasm32")] pub mod browser_ws;
#[cfg(target_arch = "wasm32")] pub mod browser_sync;
#[cfg(target_arch = "wasm32")] pub mod browser_stream;
#[cfg(target_arch = "wasm32")] pub mod browser_sync_inbound;
#[cfg(target_arch = "wasm32")] pub mod browser_chat_state_list;
#[cfg(target_arch = "wasm32")]
mod browser_web_crypto;
#[cfg(target_arch = "wasm32")]
pub use browser_web_crypto::*;

#[cfg(target_arch = "wasm32")] mod browser_crypto_batch;
#[cfg(target_arch = "wasm32")] pub use browser_crypto_batch::{bulk_decrypt_chat, bulk_encrypt_chat, bulk_master_decrypt};
#[cfg(target_arch = "wasm32")] pub mod browser_embed_write;
#[cfg(target_arch = "wasm32")] pub mod browser_embed_read;
#[cfg(target_arch = "wasm32")] pub mod browser_toon;

#[cfg(target_arch = "wasm32")]
mod browser_chat_state;
#[cfg(target_arch = "wasm32")]
mod browser_auth;
#[cfg(target_arch = "wasm32")] pub mod browser_persist;
#[cfg(target_arch = "wasm32")] pub mod browser_ws_link;
#[cfg(target_arch = "wasm32")]
pub use browser_auth::*;

#[cfg(all(test, target_arch = "wasm32"))]
mod legacy_password_test_context;

#[cfg(all(test, target_arch = "wasm32"))]
mod browser_socket_close_tests;
