//! Shared password master-envelope validation for native and browser primitives.
//! This module owns strict base64, IV/tag layout and exact master output size.
//! Primitive adapters cannot select alternative framing or plaintext policy.
//! PBKDF2 work and UTF8 semantics remain the existing deployed legacy contract.
//! Tests compile this exact source without enabling native client tests on WASM.
use super::*;
/// Unchanged deployed legacy PBKDF2 work factor; not a configurable policy.
pub(crate) const LEGACY_PASSWORD_ITERATIONS: u32 = 100_000;
/// Shared strict wire parsing for native and browser primitive implementations.
/// Base64 remains the existing STANDARD engine (no browser forgiving fallback).
pub(crate) struct PasswordMasterEnvelope {
    pub(crate) iv: [u8; 12],
    pub(crate) ciphertext: Vec<u8>,
}
pub(crate) fn password_master_envelope(ciphertext: &str, iv: &str) -> Result<PasswordMasterEnvelope> {
    let iv = STANDARD.decode(iv).map_err(|_| Error::Crypto)?;
    let iv = iv.try_into().map_err(|_| Error::Crypto)?;
    let ciphertext = STANDARD.decode(ciphertext).map_err(|_| Error::Crypto)?;
    if ciphertext.len() < 16 { return Err(Error::Crypto); }
    Ok(PasswordMasterEnvelope { iv, ciphertext })
}
pub(crate) fn password_master_from_plaintext(raw: &[u8]) -> Result<Key> {
    if raw.len() != 32 { return Err(Error::Crypto); }
    let mut master = Zeroizing::new([0u8; 32]);
    master.copy_from_slice(raw);
    Ok(master)
}
