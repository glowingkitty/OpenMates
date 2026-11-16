//! Slides presentation remote: the state a presenting device and a phone remote
//! exchange, its embed-key encryption and its ordering rule. Shared client core
//! (shells only carry the opaque ciphertext in the shell-owned
//! `slides_present_state` frame; the server relays it unread). Implements
//! `slides.present.remote-relay-private` and `slides.present.remote-one-core`
//! (`specifications/features/slides/specification.yml`). No TS original.
//!
//! The state holds only position, build step, a notes-visible flag and an
//! ordering number. Speaker notes are not representable: the wire struct
//! refuses unknown fields and has no text field besides identifiers.

use crate::client::Client;
use crate::client::embed_write::keys::{NonceSource, OsNonces, decrypt_text, encrypt_text};
use crate::error::Error;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Wire format version carried in the authenticated plaintext (`v`).
pub const PRESENT_REMOTE_VERSION: u8 = 1;
/// Largest accepted plaintext, in bytes.
pub const PRESENT_REMOTE_MAX_PLAINTEXT: usize = 512;
/// Largest accepted ciphertext, in characters (base64).
pub const PRESENT_REMOTE_MAX_CIPHERTEXT: usize = 1024;
/// Largest `seq` a browser shell can represent exactly (2^53 - 1).
pub const PRESENT_REMOTE_MAX_SEQ: u64 = 9_007_199_254_740_991;
/// AES-GCM associated data: binds the ciphertext to this purpose so an embed
/// content ciphertext cannot be replayed as a remote state or vice versa.
const AAD: &str = "slides_present_state:v1";

/// Which device produced a state.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresentRemoteOrigin {
    /// The device showing the full-screen presentation.
    Presenter,
    /// A device acting as the remote.
    Remote,
}

/// One presentation state snapshot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PresentRemoteState {
    /// Deck embed the state belongs to (authenticated).
    pub embed_id: String,
    /// Presentation session; a new presentation starts a new session id.
    pub session_id: String,
    /// Ordering number, increasing within a session.
    pub seq: u64,
    /// Current slide index.
    pub index: u32,
    /// Current build step within the slide.
    pub step: u32,
    /// Whether the presenter shows its notes (the notes themselves never travel).
    pub notes_visible: bool,
    /// False once the presentation ended.
    pub presenting: bool,
    /// Producer of this snapshot.
    pub origin: PresentRemoteOrigin,
}

/// Versioned JSON wire form. `deny_unknown_fields` keeps any extra payload,
/// such as speaker notes, from being accepted.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Wire {
    v: u8,
    embed_id: String,
    session_id: String,
    seq: u64,
    index: u32,
    step: u32,
    notes_visible: bool,
    presenting: bool,
    origin: PresentRemoteOrigin,
}

/// Typed refusal with a stable code.
#[derive(Debug, PartialEq, Eq)]
pub enum PresentRemoteError {
    /// Ciphertext longer than [`PRESENT_REMOTE_MAX_CIPHERTEXT`].
    CiphertextTooLong,
    /// Plaintext longer than [`PRESENT_REMOTE_MAX_PLAINTEXT`].
    PlaintextTooLong,
    /// Wrong key, tampered or malformed ciphertext.
    Crypto,
    /// Plaintext is not a valid state document (including unknown fields).
    Malformed,
    /// `v` is not [`PRESENT_REMOTE_VERSION`].
    UnknownVersion,
    /// The authenticated embed id differs from the expected one.
    EmbedMismatch,
    /// `seq` exceeds [`PRESENT_REMOTE_MAX_SEQ`].
    SeqOutOfRange,
    /// The embed key could not be resolved; carries the core error code.
    Key(&'static str),
}

impl PresentRemoteError {
    /// Stable code string for bindings.
    pub fn code(&self) -> &'static str {
        match self {
            Self::CiphertextTooLong => "present_remote_ciphertext_too_long",
            Self::PlaintextTooLong => "present_remote_plaintext_too_long",
            Self::Crypto => "present_remote_crypto",
            Self::Malformed => "present_remote_malformed",
            Self::UnknownVersion => "present_remote_unknown_version",
            Self::EmbedMismatch => "present_remote_embed_mismatch",
            Self::SeqOutOfRange => "present_remote_seq_out_of_range",
            Self::Key(code) => code,
        }
    }
}

/// Encrypts `state` with the deck's embed key (embed-content framing:
/// base64 of 12-byte IV, ciphertext and tag). Fresh random IV per call.
///
/// # Errors
/// `SeqOutOfRange`, `PlaintextTooLong` or `Crypto`.
pub fn encrypt_state(
    state: &PresentRemoteState,
    key: &[u8; 32],
) -> Result<String, PresentRemoteError> {
    encrypt_state_with(state, key, &mut OsNonces)
}

/// [`encrypt_state`] with a caller-supplied nonce source (tests).
///
/// # Errors
/// Same as [`encrypt_state`].
pub fn encrypt_state_with(
    state: &PresentRemoteState,
    key: &[u8; 32],
    nonces: &mut impl NonceSource,
) -> Result<String, PresentRemoteError> {
    if state.seq > PRESENT_REMOTE_MAX_SEQ {
        return Err(PresentRemoteError::SeqOutOfRange);
    }
    let wire = Wire {
        v: PRESENT_REMOTE_VERSION,
        embed_id: state.embed_id.clone(),
        session_id: state.session_id.clone(),
        seq: state.seq,
        index: state.index,
        step: state.step,
        notes_visible: state.notes_visible,
        presenting: state.presenting,
        origin: state.origin,
    };
    let plain = serde_json::to_string(&wire).map_err(|_| PresentRemoteError::Malformed)?;
    if plain.len() > PRESENT_REMOTE_MAX_PLAINTEXT {
        return Err(PresentRemoteError::PlaintextTooLong);
    }
    let sealed =
        encrypt_text(&plain, key, Some(AAD), nonces).map_err(|_| PresentRemoteError::Crypto)?;
    if sealed.len() > PRESENT_REMOTE_MAX_CIPHERTEXT {
        return Err(PresentRemoteError::CiphertextTooLong);
    }
    Ok(sealed)
}

/// Decrypts a relayed state and checks it belongs to `expected_embed_id`.
///
/// # Errors
/// `CiphertextTooLong` (checked first), `Crypto`, `PlaintextTooLong`,
/// `Malformed`, `UnknownVersion`, `SeqOutOfRange`, `EmbedMismatch`.
pub fn decrypt_state(
    ciphertext: &str,
    expected_embed_id: &str,
    key: &[u8; 32],
) -> Result<PresentRemoteState, PresentRemoteError> {
    if ciphertext.len() > PRESENT_REMOTE_MAX_CIPHERTEXT {
        return Err(PresentRemoteError::CiphertextTooLong);
    }
    let plain = decrypt_text(ciphertext, key, Some(AAD)).map_err(|_| PresentRemoteError::Crypto)?;
    if plain.len() > PRESENT_REMOTE_MAX_PLAINTEXT {
        return Err(PresentRemoteError::PlaintextTooLong);
    }
    let value: serde_json::Value =
        serde_json::from_str(&plain).map_err(|_| PresentRemoteError::Malformed)?;
    if value.get("v").and_then(serde_json::Value::as_u64) != Some(u64::from(PRESENT_REMOTE_VERSION))
    {
        return Err(PresentRemoteError::UnknownVersion);
    }
    let wire: Wire = serde_json::from_value(value).map_err(|_| PresentRemoteError::Malformed)?;
    if wire.embed_id != expected_embed_id {
        return Err(PresentRemoteError::EmbedMismatch);
    }
    if wire.seq > PRESENT_REMOTE_MAX_SEQ {
        return Err(PresentRemoteError::SeqOutOfRange);
    }
    Ok(PresentRemoteState {
        embed_id: wire.embed_id,
        session_id: wire.session_id,
        seq: wire.seq,
        index: wire.index,
        step: wire.step,
        notes_visible: wire.notes_visible,
        presenting: wire.presenting,
        origin: wire.origin,
    })
}

/// Ordering of states for one embed: decides which relayed state a device applies.
#[derive(Debug, Default)]
pub struct PresentRemoteOrdering {
    current: Option<PresentRemoteState>,
}

impl PresentRemoteOrdering {
    /// Empty ordering: the first state is accepted.
    pub fn new() -> Self {
        Self::default()
    }

    /// True when `state` should be applied (and is remembered). Within a
    /// session only a higher `seq` wins. A different session replaces the
    /// current one only if it is presenting or the current one has ended.
    pub fn accept(&mut self, state: &PresentRemoteState) -> bool {
        let take = match &self.current {
            None => true,
            Some(old) if old.session_id == state.session_id => state.seq > old.seq,
            Some(old) => state.presenting || !old.presenting,
        };
        if take {
            self.current = Some(state.clone());
        }
        take
    }
}

/// Ordering per embed, as a Worker keeps it for all open decks.
#[derive(Debug, Default)]
pub struct PresentRemoteOrderings {
    by_embed: HashMap<String, PresentRemoteOrdering>,
}

impl PresentRemoteOrderings {
    /// [`PresentRemoteOrdering::accept`] on the ordering of `state.embed_id`.
    pub fn accept(&mut self, state: &PresentRemoteState) -> bool {
        self.by_embed
            .entry(state.embed_id.clone())
            .or_default()
            .accept(state)
    }
}

impl Client {
    /// Encrypts `state` with the deck's embed key, resolved inside the core.
    ///
    /// # Errors
    /// `Key` when the embed key is unavailable, else see [`encrypt_state`].
    pub async fn present_remote_encrypt(
        &mut self,
        state: &PresentRemoteState,
    ) -> Result<String, PresentRemoteError> {
        let key = self
            .edit_embed_key(&state.embed_id)
            .await
            .map_err(key_error)?;
        encrypt_state(state, &key)
    }

    /// Decrypts a relayed state with the embed key of `embed_id`.
    ///
    /// # Errors
    /// `Key` when the embed key is unavailable, else see [`decrypt_state`].
    pub async fn present_remote_decrypt(
        &mut self,
        embed_id: &str,
        ciphertext: &str,
    ) -> Result<PresentRemoteState, PresentRemoteError> {
        // Length is checked before any key lookup so oversized frames cost nothing.
        if ciphertext.len() > PRESENT_REMOTE_MAX_CIPHERTEXT {
            return Err(PresentRemoteError::CiphertextTooLong);
        }
        let key = self.edit_embed_key(embed_id).await.map_err(key_error)?;
        decrypt_state(ciphertext, embed_id, &key)
    }
}

fn key_error(error: Error) -> PresentRemoteError {
    PresentRemoteError::Key(match error {
        Error::Unavailable { code, .. } => code,
        _ => "embed_key_unavailable",
    })
}

#[cfg(test)]
#[path = "present_remote_tests.rs"]
mod present_remote_tests;
