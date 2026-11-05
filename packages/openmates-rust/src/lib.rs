//! Headless OpenMates SDK. Credentials, consent and privacy policy are supplied
//! explicitly by the caller; importing or constructing a client never reads a
//! CLI profile, prompts for input, starts a terminal, or opens a browser.
#![forbid(unsafe_code)]
pub mod account;
pub mod chat_state;
pub mod client;
pub mod crypto;
pub mod error;
pub mod mentions;
pub mod mentions_list;
pub mod model;
pub mod pairing;
pub mod pii_display_aliases;
mod platform;
pub mod privacy;
pub mod project_task_sync;
pub mod remote_access_crypto;
#[cfg(all(feature = "workflow-yaml", not(target_arch = "wasm32")))]
pub mod remote_command;
pub mod session;
pub mod task_order;
pub mod upload_privacy;
pub mod web_search;
pub mod web_search_json;
#[cfg(test)]
mod web_search_tests;
pub use client::{
    Client, ClientIdentity, ClientOptions, PasswordLoginOptions, CredentialEvent, CredentialSnapshot, PairChallenge,
    SendConsentPolicy, SendMemoryRequest, SendOptions, SendOutcome, SendQueueMode, SendStatus,
};
pub use error::{Error, Result};
pub use session::Session;

pub mod generated;
pub mod sdk;
pub mod sdk_chats;
pub mod sdk_drafts;
pub mod sdk_history;
pub mod sdk_docs;
pub mod sdk_wikipedia;
pub mod sdk_embeds;
pub use sdk::{AnonymousMessage, ApiKey, OpenMates, SdkCredentials, SdkOptions};

pub mod work;
pub mod web_auth;
pub mod ws_link;
