//! Headless OpenMates SDK. Credentials, consent and privacy policy are supplied
//! explicitly by the caller; importing or constructing a client never reads a
//! CLI profile, prompts for input, starts a terminal, or opens a browser.
#![forbid(unsafe_code)]
pub mod account;
pub mod chat_state;
pub mod client;
pub mod crypto;
pub mod embed_read;
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
#[cfg(all(feature = "workflow-yaml", unix))]
pub mod source_host;
pub mod session;
pub mod task_order;
pub mod test_result_embed;
pub mod toon_decode;
pub mod upload_privacy;
pub mod web_persist;
pub mod web_connected_accounts;
pub mod web_ws;
pub mod web_search;
pub mod web_search_chats;
pub mod web_search_corpus;
pub mod web_search_json;
pub mod web_search_query;
pub mod web_send_prep;
pub mod web_apps;
pub mod web_settings;
pub mod web_settings_privacy;
pub mod web_parse;
pub mod web_transfer;
pub mod web_keys;
pub mod web_key_bulk;
#[cfg(test)]
mod web_key_bulk_tests;
pub mod web_key_state;
#[cfg(test)]
mod web_key_state_tests;
#[cfg(test)]
mod web_keys_tests;
/// Project decisions of the web `projectDecide` op (projectState policy twin).
pub mod web_projects;
#[cfg(test)]
mod web_projects_tests;
pub mod web_guest;
#[cfg(test)]
mod web_guest_tests;
/// Continue-carousel reminder index and priority order of the web `continueDecide` op.
pub mod web_continue;
#[cfg(test)]
mod web_continue_tests;
pub mod web_share_state;
#[cfg(test)]
mod web_share_state_tests;
/// User Plans (later Tasks/Teams) decisions of the web `work` op.
pub mod web_work;
pub mod web_stream;
pub mod web_sync;
pub mod web_chat_state;
#[cfg(test)]
mod web_search_bench;
#[cfg(test)]
mod web_search_chats_tests;
#[cfg(test)]
mod web_search_query_tests;
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
pub mod sdk_chat_rewrite;
pub mod sdk_drafts;
pub mod sdk_history;
pub mod sdk_docs;
pub mod sdk_wikipedia;
pub mod sdk_ops;
pub mod sdk_billing;
pub mod sdk_settings;
pub mod sdk_reminders;
pub mod sdk_notifications;
pub mod sdk_finance;
pub mod sdk_connected_accounts;
pub mod sdk_embeds;
pub mod sdk_benchmark;
pub mod sdk_design;
pub mod sdk_feedback;
pub mod sdk_ideabucket;
pub mod sdk_inspirations;
pub mod sdk_learning_mode;
pub mod sdk_memories;
pub mod sdk_account_imports;
pub mod sdk_new_chat_suggestions;
pub mod sdk_public_utilities;
pub mod sdk_transport;
pub use sdk::{AnonymousMessage, ApiKey, OpenMates, SdkCredentials, SdkOptions};

pub mod work;
pub mod web_auth;
pub mod web_composer;
pub mod ws_link;
