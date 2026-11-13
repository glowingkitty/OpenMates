//! Explicit AEAD platform adapter for the shared crypto core.
//!
//! Rust owns every crypto format and policy (chat-content OM/legacy framing and
//! attempt order, master Formats C/D, share and media layouts). Only the raw
//! AES-256-GCM primitive (12-byte IV, appended 128-bit tag, empty AAD) runs
//! behind [`AeadProvider`], so each platform supplies its fastest primitive:
//! - native CLI/SDK: [`NativeAead`] (RustCrypto `aes-gcm`, constant time);
//! - web: the browser bindings' WebCrypto provider inside the shared Worker;
//! - Apple, later: CryptoKit or [`NativeAead`] in process.
//!
//! The interface is FFI friendly: plain bytes in and out, futures for every
//! primitive call, and no wasm-bindgen or platform types. An imported key is an
//! [`AeadBatchKey`]: an [`AeadKey`] (the same contract `MasterCapability` uses
//! for opaque keys, so a platform may keep it non-extractable) that may also
//! issue a whole list of primitive calls at once (one platform call per list
//! instead of one per item). `Err(Error::Crypto)` from a decrypt means the tag
//! did not authenticate (the next planned attempt runs); any other error aborts
//! the operation.
use super::chat_key_policy::{self as policy, ChatContentOutcome};
pub use super::master::MasterCrypto as AeadKey;
use super::master::{MasterCryptoBounds, MasterCryptoFuture};
use super::*;
use futures_util::future::join_all;
use std::{future::Future, pin::Pin};

/// One primitive call of a list: 12-byte IV and the input (plaintext, or
/// ciphertext with its appended 128-bit tag).
#[derive(Clone, Copy, Debug)]
pub struct AeadOp<'a> {
    pub iv: &'a [u8; 12],
    pub input: &'a [u8],
}

/// Per-op results of a list, in op order.
pub type AeadBatch = Vec<Result<Zeroizing<Vec<u8>>>>;

#[cfg(target_arch = "wasm32")]
pub type AeadBatchFuture<'a> = Pin<Box<dyn Future<Output = AeadBatch> + 'a>>;
#[cfg(not(target_arch = "wasm32"))]
pub type AeadBatchFuture<'a> = Pin<Box<dyn Future<Output = AeadBatch> + Send + 'a>>;

/// An imported AEAD key. The defaults issue every op of a list concurrently
/// through the single-op [`AeadKey`] methods; a platform overrides them when
/// one call per list is cheaper. Each result must be in op order, one per op.
pub trait AeadBatchKey: AeadKey {
    fn decrypt_many<'a>(&'a self, ops: &'a [AeadOp<'a>]) -> AeadBatchFuture<'a> {
        Box::pin(join_all(ops.iter().map(|op| self.decrypt(op.iv, op.input))))
    }
    fn encrypt_many<'a>(&'a self, ops: &'a [AeadOp<'a>]) -> AeadBatchFuture<'a> {
        Box::pin(join_all(ops.iter().map(|op| self.encrypt(op.iv, op.input))))
    }
}

#[cfg(target_arch = "wasm32")]
pub type SharedAeadKey = std::rc::Rc<dyn AeadBatchKey>;
#[cfg(not(target_arch = "wasm32"))]
pub type SharedAeadKey = std::sync::Arc<dyn AeadBatchKey>;

/// Wraps one platform key handle as a [`SharedAeadKey`].
pub fn share_aead_key<K: AeadBatchKey + 'static>(key: K) -> SharedAeadKey {
    #[cfg(target_arch = "wasm32")]
    return std::rc::Rc::new(key);
    #[cfg(not(target_arch = "wasm32"))]
    return std::sync::Arc::new(key);
}

#[cfg(target_arch = "wasm32")]
pub type AeadKeyFuture<'a> = Pin<Box<dyn Future<Output = Result<SharedAeadKey>> + 'a>>;
#[cfg(not(target_arch = "wasm32"))]
pub type AeadKeyFuture<'a> = Pin<Box<dyn Future<Output = Result<SharedAeadKey>> + Send + 'a>>;

/// Imports raw 32-byte AES-256-GCM keys for one platform's primitive.
pub trait AeadProvider: MasterCryptoBounds {
    fn import_key<'a>(&'a self, raw: &'a [u8; 32]) -> AeadKeyFuture<'a>;
}

/// RustCrypto AES-256-GCM. Futures are ready on first poll.
#[derive(Clone, Copy, Debug, Default)]
pub struct NativeAead;

struct NativeAeadKey(Aes256Gcm);

impl NativeAeadKey {
    fn run(&self, iv: &[u8; 12], input: &[u8], encrypt: bool) -> Result<Zeroizing<Vec<u8>>> {
        let payload = Payload {
            msg: input,
            aad: &[],
        };
        let nonce = Nonce::from_slice(iv);
        let output = if encrypt {
            self.0.encrypt(nonce, payload)
        } else {
            self.0.decrypt(nonce, payload)
        };
        output.map(Zeroizing::new).map_err(|_| Error::Crypto)
    }
}

impl AeadKey for NativeAeadKey {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plaintext: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(std::future::ready(self.run(iv, plaintext, true)))
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], sealed: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(std::future::ready(self.run(iv, sealed, false)))
    }
}

impl AeadBatchKey for NativeAeadKey {}

impl AeadProvider for NativeAead {
    fn import_key<'a>(&'a self, raw: &'a [u8; 32]) -> AeadKeyFuture<'a> {
        Box::pin(std::future::ready(Ok(share_aead_key(NativeAeadKey(
            Aes256Gcm::new(raw.into()),
        )))))
    }
}

fn iv_at(bytes: &[u8], range: (usize, usize)) -> Result<&[u8; 12]> {
    bytes
        .get(range.0..range.1)
        .and_then(|iv| iv.try_into().ok())
        .ok_or(Error::Crypto)
}

fn batch_mismatch() -> Error {
    Error::Unavailable {
        code: "aead_provider",
        reason: "AEAD_BATCH_LENGTH_MISMATCH",
    }
}

/// `decryptWithChatKey` over a list: the planned authenticated attempts of
/// every item run as one [`AeadBatchKey::decrypt_many`] call per attempt round
/// (round 1: each item's first attempt; round 2: the legacy fallback of the
/// items whose first attempt did not authenticate).
pub async fn open_chat_batch<S: AsRef<str>>(
    key: &dyn AeadBatchKey,
    raw: &[u8; 32],
    items: &[S],
) -> Result<Vec<ChatContentOutcome>> {
    let decoded: Vec<Option<Zeroizing<Vec<u8>>>> = items
        .iter()
        .map(|item| policy::decode_web_base64(item.as_ref()).ok())
        .collect();
    let plans: Vec<Option<policy::ChatContentPlan>> = decoded
        .iter()
        .map(|bytes| {
            bytes
                .as_ref()
                .map(|bytes| policy::plan_chat_content(bytes, raw))
        })
        .collect();
    let mut outcomes: Vec<Option<ChatContentOutcome>> = items.iter().map(|_| None).collect();
    let mut next = vec![0usize; items.len()];
    loop {
        let mut pending = Vec::new();
        let mut ops = Vec::new();
        for (index, (bytes, plan)) in decoded.iter().zip(&plans).enumerate() {
            let (Some(bytes), Some(plan)) = (bytes, plan) else {
                continue;
            };
            if outcomes[index].is_some() {
                continue;
            }
            // An attempt whose IV range is unusable cannot authenticate; skip it.
            while let Some(attempt) = plan.attempts.get(next[index]) {
                if let Ok(iv) = iv_at(bytes, attempt.iv) {
                    pending.push(index);
                    ops.push(AeadOp {
                        iv,
                        input: &bytes[attempt.body.0..attempt.body.1],
                    });
                    break;
                }
                next[index] += 1;
            }
        }
        if ops.is_empty() {
            break;
        }
        let results = key.decrypt_many(&ops).await;
        if results.len() != ops.len() {
            return Err(batch_mismatch());
        }
        for (index, result) in pending.into_iter().zip(results) {
            match result {
                Ok(plain) => outcomes[index] = Some(ChatContentOutcome::Plaintext(plain)),
                Err(Error::Crypto) => next[index] += 1,
                Err(error) => return Err(error),
            }
        }
    }
    Ok(outcomes
        .into_iter()
        .zip(plans)
        .map(|(outcome, plan)| {
            outcome.unwrap_or(match plan.and_then(|plan| plan.fingerprint_mismatch) {
                Some(stored) => ChatContentOutcome::FingerprintMismatch(stored),
                None => ChatContentOutcome::Failed,
            })
        })
        .collect())
}

/// `decryptWithChatKey` over a provider key imported from `raw`.
pub async fn open_chat_content(
    key: &dyn AeadBatchKey,
    raw: &[u8; 32],
    ciphertext: &str,
) -> Result<ChatContentOutcome> {
    open_chat_batch(key, raw, &[ciphertext])
        .await?
        .pop()
        .ok_or_else(batch_mismatch)
}

/// `encryptWithChatKey` over a list: OM framing with a fresh random IV per
/// item, one [`AeadBatchKey::encrypt_many`] call; fails as a whole like a TS
/// `Promise.all`.
pub async fn seal_chat_batch<P: AsRef<[u8]>>(
    key: &dyn AeadBatchKey,
    raw: &[u8; 32],
    items: &[P],
) -> Result<Vec<String>> {
    let ivs: Vec<[u8; 12]> = items.iter().map(|_| share::random_iv()).collect();
    let ops: Vec<AeadOp> = ivs
        .iter()
        .zip(items)
        .map(|(iv, item)| AeadOp {
            iv,
            input: item.as_ref(),
        })
        .collect();
    let sealed = key.encrypt_many(&ops).await;
    if sealed.len() != ops.len() {
        return Err(batch_mismatch());
    }
    ivs.iter()
        .zip(sealed)
        .map(|(iv, sealed)| Ok(policy::frame_chat_content(raw, iv, &sealed?)))
        .collect()
}

/// `encryptWithChatKey`: OM framing with a fresh random IV.
pub async fn seal_chat_content(
    key: &dyn AeadBatchKey,
    raw: &[u8; 32],
    plaintext: &[u8],
) -> Result<String> {
    seal_chat_batch(key, raw, &[plaintext])
        .await?
        .pop()
        .ok_or_else(batch_mismatch)
}

/// Formats C/D read (`decryptChatKeyWithMasterKey`): one authenticated attempt.
pub async fn open_master_envelope(
    key: &dyn AeadKey,
    ciphertext: &str,
) -> Result<Zeroizing<Vec<u8>>> {
    let combined = policy::open_master_envelope(ciphertext)?;
    key.decrypt(iv_at(&combined, (0, 12))?, &combined[12..])
        .await
}

/// List form of [`open_master_envelope`]; each item fails on its own.
pub async fn open_master_batch<S: AsRef<str>>(
    key: &dyn AeadKey,
    items: &[S],
) -> Vec<Result<Zeroizing<Vec<u8>>>> {
    join_all(
        items
            .iter()
            .map(|item| open_master_envelope(key, item.as_ref())),
    )
    .await
}
