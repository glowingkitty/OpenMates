//! Test-only context for the exact canonical private SDK crypto source files.
//! Existing bindings DedicatedWorker test configuration and lock are reused.
//! The SDK dependency's native-only tests are never enabled on browser targets.
//! Key/Error and native unwrap comparator are the actual public SDK identities.
//! No copied parser/primitive, public test export or runtime dependency exists.
use openmates_sdk::{Error, Result};
use openmates_sdk::crypto::{Key, encode_key, unwrap_password_master_key};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use zeroize::Zeroizing;
#[path = "../../openmates-rust/src/crypto/password_master.rs"]
mod password_master;
use password_master::*;
#[path = "../../openmates-rust/src/crypto/browser_legacy.rs"]
mod browser_legacy;
use browser_legacy::*;
#[path = "legacy_password_tests.rs"]
mod tests;
