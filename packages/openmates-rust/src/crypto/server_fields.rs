//! Wire codec for server fields read by deployed MetadataEncryptor (Formats C/D,
//! embed/object wrappers and activity). Public generic/native encryption and
//! local vault/snapshot formats are separate and intentionally unchanged.
use super::*;
/// Always base64(12-byte IV || AES-GCM ciphertext ||128-bit tag). AAD is passed
/// byte-for-byte from the Rust field protocol; no implicit scope/key derivation.
pub(crate) fn encrypt_bytes(plaintext:&[u8],key:&[u8;32],aad:&[u8])->Result<String>{
    let mut iv=[0u8;12];OsRng.fill_bytes(&mut iv);
    let mut bytes=iv.to_vec();bytes.extend(encrypt_aead(plaintext,key,&iv,aad)?);Ok(STANDARD.encode(bytes))
}
pub(crate) fn encrypt_text(plaintext:&str,key:&[u8;32],aad:&[u8])->Result<String>{encrypt_bytes(plaintext.as_bytes(),key,aad)}
/// Dual authenticated read preserves already-accepted native framed ciphertext
/// while accepting browser legacy fields, including a valid OM-looking IV.
/// Header guesses never release bytes until the exact caller AAD/tag verifies.
pub(crate) fn decrypt_bytes(ciphertext:&str,key:&[u8;32],aad:&[u8])->Result<Zeroizing<Vec<u8>>>{
    if aad.is_empty(){return super::decrypt_bytes(ciphertext,key);}
    let combined=STANDARD.decode(ciphertext).map_err(|_|Error::Crypto)?;
    if combined.len()<28{return Err(Error::Crypto);}
    if combined.len()>=34&&combined.starts_with(b"OM")&&(combined[2..6]==key_fingerprint(key)||combined[2..6]==[1,0,0,0]) {
        if let Ok(plain)=decrypt_aead(&combined[18..],key,&combined[6..18],aad){return Ok(plain);}
    }
    decrypt_aead(&combined[12..],key,&combined[..12],aad)
}
pub(crate) fn decrypt_text(ciphertext:&str,key:&[u8;32],aad:&[u8])->Result<String>{
    let plain=decrypt_bytes(ciphertext,key,aad)?;Ok(String::from_utf8_lossy(&plain).into_owned())
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="server_fields_tests.rs"]
mod tests;
