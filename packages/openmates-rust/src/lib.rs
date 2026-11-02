//! Headless OpenMates SDK. Credentials, consent and privacy policy are supplied
//! explicitly by the caller; importing or constructing a client never reads a
//! CLI profile, prompts for input, starts a terminal, or opens a browser.
#![forbid(unsafe_code)]
pub mod account;
pub mod client;
pub mod crypto;
pub mod error;
pub mod model;
pub mod pairing;
mod platform;
pub mod privacy;
pub mod project_task_sync;
pub mod remote_access_crypto;
pub mod session;
pub mod task_order;
pub use client::{
    Client, ClientIdentity, ClientOptions, PasswordLoginOptions, CredentialEvent, CredentialSnapshot, PairChallenge,
    SendConsentPolicy, SendMemoryRequest, SendOptions, SendOutcome, SendQueueMode, SendStatus,
};
pub use error::{Error, Result};
pub use session::Session;

pub mod generated;
pub mod sdk;
pub mod sdk_drafts;
pub mod sdk_history;
pub mod sdk_docs;
pub mod sdk_wikipedia;
pub mod sdk_embeds;
pub use sdk::{AnonymousMessage, ApiKey, OpenMates, SdkCredentials, SdkOptions};

pub mod work;
