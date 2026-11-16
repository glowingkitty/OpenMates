//! Slides "presentation remote" for the Apple shell: encrypts and decrypts the
//! `slides_present_state` payload with the deck's embed key inside the core and
//! keeps the per-embed ordering that decides which relayed state is applied.
//! The wire frame itself (`slides_present_state`, `…_rejected`) is shell-owned and
//! travels through the unowned-frame pass-through. Speaker notes never travel.
//! Spec: `specifications/features/slides` (`slides.present.remote-*`).

use crate::view_core::ViewModelCore;
use crate::view_embeds::EmbedEditError;
use openmates_sdk::client::shared_items::present_remote::{
    PresentRemoteError, PresentRemoteOrderings, PresentRemoteOrigin, PresentRemoteState,
};
use std::sync::{Mutex, MutexGuard, PoisonError};

/// Which device produced a state.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SlidesRemoteOriginRecord {
    /// The device showing the full-screen presentation.
    Presenter,
    /// A device acting as the remote.
    Remote,
}

/// One presentation state snapshot (same fields as the web `PresentRemoteState`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlidesRemoteStateRecord {
    /// Deck embed the state belongs to.
    pub embed_id: String,
    /// Presentation session id.
    pub session_id: String,
    /// Ordering number, increasing within a session (at most 2^53 - 1).
    pub seq: u64,
    /// Current slide index.
    pub index: u32,
    /// Current build step.
    pub step: u32,
    /// Whether the presenter shows its notes.
    pub notes_visible: bool,
    /// False once the presentation ended.
    pub presenting: bool,
    /// Producer of this snapshot.
    pub origin: SlidesRemoteOriginRecord,
}

/// Typed refusal; each case has a stable `code` string.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error, uniffi::Error)]
pub enum SlidesRemoteError {
    /// Ciphertext too long.
    #[error("present_remote_ciphertext_too_long")]
    CiphertextTooLong,
    /// Plaintext too long.
    #[error("present_remote_plaintext_too_long")]
    PlaintextTooLong,
    /// Wrong key, tampered or malformed ciphertext.
    #[error("present_remote_crypto")]
    Crypto,
    /// Not a valid state document.
    #[error("present_remote_malformed")]
    Malformed,
    /// Unknown wire version.
    #[error("present_remote_unknown_version")]
    UnknownVersion,
    /// The state belongs to another embed.
    #[error("present_remote_embed_mismatch")]
    EmbedMismatch,
    /// `seq` too large.
    #[error("present_remote_seq_out_of_range")]
    SeqOutOfRange,
    /// The embed key or the session is unavailable; `code` is stable.
    #[error("{code}")]
    Unavailable {
        /// Stable machine code.
        code: String,
    },
}

impl From<PresentRemoteError> for SlidesRemoteError {
    fn from(error: PresentRemoteError) -> Self {
        match error {
            PresentRemoteError::CiphertextTooLong => Self::CiphertextTooLong,
            PresentRemoteError::PlaintextTooLong => Self::PlaintextTooLong,
            PresentRemoteError::Crypto => Self::Crypto,
            PresentRemoteError::Malformed => Self::Malformed,
            PresentRemoteError::UnknownVersion => Self::UnknownVersion,
            PresentRemoteError::EmbedMismatch => Self::EmbedMismatch,
            PresentRemoteError::SeqOutOfRange => Self::SeqOutOfRange,
            PresentRemoteError::Key(code) => Self::Unavailable { code: code.into() },
        }
    }
}

impl From<EmbedEditError> for SlidesRemoteError {
    fn from(error: EmbedEditError) -> Self {
        Self::Unavailable {
            code: error.to_string(),
        }
    }
}

impl From<SlidesRemoteOriginRecord> for PresentRemoteOrigin {
    fn from(origin: SlidesRemoteOriginRecord) -> Self {
        match origin {
            SlidesRemoteOriginRecord::Presenter => Self::Presenter,
            SlidesRemoteOriginRecord::Remote => Self::Remote,
        }
    }
}

impl From<PresentRemoteOrigin> for SlidesRemoteOriginRecord {
    fn from(origin: PresentRemoteOrigin) -> Self {
        match origin {
            PresentRemoteOrigin::Presenter => Self::Presenter,
            PresentRemoteOrigin::Remote => Self::Remote,
        }
    }
}

impl From<SlidesRemoteStateRecord> for PresentRemoteState {
    fn from(state: SlidesRemoteStateRecord) -> Self {
        Self {
            embed_id: state.embed_id,
            session_id: state.session_id,
            seq: state.seq,
            index: state.index,
            step: state.step,
            notes_visible: state.notes_visible,
            presenting: state.presenting,
            origin: state.origin.into(),
        }
    }
}

impl From<PresentRemoteState> for SlidesRemoteStateRecord {
    fn from(state: PresentRemoteState) -> Self {
        Self {
            embed_id: state.embed_id,
            session_id: state.session_id,
            seq: state.seq,
            index: state.index,
            step: state.step,
            notes_visible: state.notes_visible,
            presenting: state.presenting,
            origin: state.origin.into(),
        }
    }
}

/// Per-embed ordering of relayed states: decides which state a device applies.
/// Create one per signed-in session and keep it next to the remote view model.
#[derive(uniffi::Object, Default)]
pub struct SlidesRemoteOrderings {
    inner: Mutex<PresentRemoteOrderings>,
}

impl SlidesRemoteOrderings {
    fn lock(&self) -> MutexGuard<'_, PresentRemoteOrderings> {
        // The ordering holds no cross-field invariant a panic could break midway.
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[uniffi::export]
impl SlidesRemoteOrderings {
    /// Empty orderings: the first state of each embed is accepted.
    #[uniffi::constructor]
    pub fn new() -> std::sync::Arc<Self> {
        std::sync::Arc::new(Self::default())
    }

    /// `true` when `state` should be applied (and is remembered).
    pub fn accept(&self, state: SlidesRemoteStateRecord) -> bool {
        self.lock().accept(&state.into())
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Encrypt `state` with the deck's embed key (resolved in the core) for
    /// the `slides_present_state` frame.
    ///
    /// # Errors
    /// `SeqOutOfRange`, `PlaintextTooLong`, `CiphertextTooLong`, `Crypto`,
    /// `Unavailable` (no embed key, signed out, busy actor).
    pub async fn slides_remote_encrypt(
        &self,
        state: SlidesRemoteStateRecord,
    ) -> std::result::Result<String, SlidesRemoteError> {
        let state: PresentRemoteState = state.into();
        let sealed = self
            .embed_command(None, move |client| {
                Box::pin(async move { Ok(client.present_remote_encrypt(&state).await) })
            })
            .await?;
        Ok(sealed?)
    }

    /// Decrypt a relayed `slides_present_state` ciphertext of `embed_id`.
    ///
    /// # Errors
    /// `CiphertextTooLong`, `Crypto`, `Malformed`, `UnknownVersion`,
    /// `EmbedMismatch`, `SeqOutOfRange`, `Unavailable`.
    pub async fn slides_remote_decrypt(
        &self,
        embed_id: String,
        ciphertext: String,
    ) -> std::result::Result<SlidesRemoteStateRecord, SlidesRemoteError> {
        let state = self
            .embed_command(None, move |client| {
                Box::pin(async move { Ok(client.present_remote_decrypt(&embed_id, &ciphertext).await) })
            })
            .await?;
        Ok(state?.into())
    }
}
