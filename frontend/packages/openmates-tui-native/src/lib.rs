#![forbid(unsafe_code)]
//! OpenMates in Rust: `cargo install openmates` installs the CLI/TUI;
//! `cargo add openmates --no-default-features` gives the SDK only.

/// The headless, end-to-end encrypted OpenMates SDK.
pub use openmates_sdk as sdk;

#[cfg(feature = "cli")]
pub mod cli;
#[cfg(feature = "cli")]
pub mod client;
#[cfg(feature = "cli")]
pub mod completion_recovery_adapter;
#[cfg(feature = "cli")]
pub mod crypto;
#[cfg(feature = "cli")]
pub mod error;
#[cfg(feature = "cli")]
pub mod local_zone;
#[cfg(feature = "cli")]
pub mod model;
#[cfg(feature = "cli")]
pub mod native_cache_clock;
#[cfg(feature = "cli")]
pub mod pairing;
#[cfg(feature = "cli")]
pub mod privacy;
#[cfg(feature = "cli")]
pub mod profile;
#[cfg(feature = "cli")]
pub mod project_task_cache;
#[cfg(feature = "cli")]
pub mod project_task_foreground;
#[cfg(feature = "cli")]
pub mod runtime_store;
#[cfg(feature = "cli")]
pub mod server;
#[cfg(feature = "cli")]
pub mod session_runtime;
#[cfg(feature = "cli")]
pub mod storage;
#[cfg(feature = "cli")]
pub mod task_delivery;
#[cfg(feature = "cli")]
mod task_order;
#[cfg(feature = "cli")]
pub mod ui;
