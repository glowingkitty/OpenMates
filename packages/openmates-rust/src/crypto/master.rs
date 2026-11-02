//! Master AES capability. Rust owns envelopes; adapters execute only AEAD.
//! Local instance equality is replacement fencing, never account ownership.
use super::*;
#[cfg(target_arch = "wasm32")]
use std::rc::Rc as Shared;
#[cfg(not(target_arch = "wasm32"))]
use std::sync::Arc as Shared;
use std::{future::Future, pin::Pin};
use zeroize::Zeroize;
#[cfg(target_arch = "wasm32")]
pub type MasterCryptoFuture<'a> = Pin<Box<dyn Future<Output = Result<Zeroizing<Vec<u8>>>> + 'a>>;
#[cfg(not(target_arch = "wasm32"))]
pub type MasterCryptoFuture<'a> =
    Pin<Box<dyn Future<Output = Result<Zeroizing<Vec<u8>>>> + Send + 'a>>;
#[cfg(target_arch = "wasm32")]
pub trait MasterCryptoBounds {}
#[cfg(target_arch = "wasm32")]
impl<T: ?Sized> MasterCryptoBounds for T {}
#[cfg(not(target_arch = "wasm32"))]
pub trait MasterCryptoBounds: Send + Sync {}
#[cfg(not(target_arch = "wasm32"))]
impl<T: Send + Sync + ?Sized> MasterCryptoBounds for T {}
/// AES-GCM256, twelve-byte IV, appended128-bit tag, empty AAD. The owning
/// worker validates actual key type/algorithm/usages before exposing the port.
/// This trait grants neither key ownership nor credential/native export rights.
pub trait MasterCrypto: MasterCryptoBounds {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plaintext: &'a [u8]) -> MasterCryptoFuture<'a>;
    fn decrypt<'a>(
        &'a self,
        iv: &'a [u8; 12],
        ciphertext_and_tag: &'a [u8],
    ) -> MasterCryptoFuture<'a>;
}
enum Material {
    Native(Key),
    // Real extractable browser material uses deployed MetadataEncryptor write
    // format while retaining the already-accepted raw/native read formats.
    BrowserRaw(Key),
    Opaque(Shared<dyn MasterCrypto>),
}
struct Instance {
    material: Material,
    cancel: tokio_util::sync::CancellationToken,
    id: String,
}
/// Nonserializable/non-Debug master resource; cloning retains the same local
/// revocation instance. No browser resource is asserted Send or Sync.
#[derive(Clone)]
pub struct MasterCapability {
    instance: Shared<Instance>,
}
impl MasterCapability {
    pub(crate) fn from_native(key: Key) -> Self {
        Self::new(Material::Native(key))
    }
    pub(crate) fn from_browser_raw(key: Key) -> Self {
        Self::new(Material::BrowserRaw(key))
    }
    #[cfg(target_arch = "wasm32")]
    pub fn from_browser_port(port: Shared<dyn MasterCrypto>) -> Self {
        Self::new(Material::Opaque(port))
    }
    #[cfg(all(test, not(target_arch = "wasm32")))]
    pub(crate) fn opaque_for_test(port: Shared<dyn MasterCrypto>) -> Self {
        Self::new(Material::Opaque(port))
    }
    fn new(material: Material) -> Self {
        Self {
            instance: Shared::new(Instance {
                material,
                cancel: tokio_util::sync::CancellationToken::new(),
                id: uuid::Uuid::new_v4().to_string(),
            }),
        }
    }
    pub fn invalidate(&self) {
        self.instance.cancel.cancel();
    }
    // Internal lifetime observation only; no authority, export or cancellation
    // reset is exposed by waiting for this already-owned resource revocation.
    pub(crate) async fn cancelled(&self){self.instance.cancel.cancelled().await;}

    pub fn same_instance(&self, other: &Self) -> bool {
        Shared::ptr_eq(&self.instance, &other.instance)
    }
    pub(crate) fn instance_binding(&self) -> &str {
        &self.instance.id
    }
    pub(crate) fn native_key(&self) -> Result<&Key> {
        self.current()?;
        match &self.instance.material {
            Material::Native(key) | Material::BrowserRaw(key) => Ok(key),
            Material::Opaque(_) => Err(Error::Unavailable {
                code: "master_key_extraction_unavailable",
                reason: "THIS_OPERATION_REQUIRES_EXTRACTABLE_MASTER_KEY_MATERIAL",
            }),
        }
    }
    pub(crate) fn ensure_current(&self) -> Result<()> {
        self.current()
    }
    fn current(&self) -> Result<()> {
        if self.instance.cancel.is_cancelled() {
            Err(Error::Cancelled)
        } else {
            Ok(())
        }
    }
    fn release(&self, mut bytes: Zeroizing<Vec<u8>>) -> Result<Zeroizing<Vec<u8>>> {
        if let Err(error) = self.current() {
            bytes.zeroize();
            return Err(error);
        }
        Ok(bytes)
    }
    pub async fn encrypt_bytes(&self, plaintext: &[u8]) -> Result<String> {
        self.current()?;
        match &self.instance.material {
            Material::Native(key) => {
                let output = super::encrypt_bytes(plaintext, key)?;
                self.current()?;
                Ok(output)
            }
            Material::BrowserRaw(key) => {
                let output=super::server_fields::encrypt_bytes(plaintext,key,&[])?;
                self.current()?;
                Ok(output)
            }
            Material::Opaque(port) => {
                let mut iv = [0u8; 12];
                OsRng.fill_bytes(&mut iv);
                let result = port.encrypt(&iv, plaintext).await;
                self.current()?;
                let ciphertext = self.release(result?)?;
                if ciphertext.len() != plaintext.len().checked_add(16).ok_or(Error::Crypto)? {
                    return Err(Error::Crypto);
                }
                // Exact existing browser Format C/D, not native OM framing.
                let mut combined = Vec::with_capacity(12 + ciphertext.len());
                combined.extend_from_slice(&iv);
                combined.extend_from_slice(&ciphertext);
                let output = STANDARD.encode(combined);
                self.current()?;
                Ok(output)
            }
        }
    }
    /// Private protocol-field writer. Deployed metadata/draft/wrapper readers
    /// require IV||ciphertext||tag. Generic native/vault codecs stay unchanged.
    pub(crate) async fn encrypt_server_bytes(&self,plaintext:&[u8])->Result<String> {
        self.current()?;
        match &self.instance.material {
            Material::Native(key)|Material::BrowserRaw(key)=>{
                let output=super::server_fields::encrypt_bytes(plaintext,key,&[])?;
                self.current()?;
                Ok(output)
            }
            Material::Opaque(_)=>self.encrypt_bytes(plaintext).await,
        }
    }
    pub async fn decrypt_bytes(&self, ciphertext: &str) -> Result<Zeroizing<Vec<u8>>> {
        self.current()?;
        match &self.instance.material {
            Material::Native(key) | Material::BrowserRaw(key) => self.release(super::decrypt_bytes(ciphertext, key)?),
            Material::Opaque(port) => {
                let combined = decode_browser_base64(ciphertext)?;
                if combined.len() < 12 + 16 {
                    return Err(Error::Crypto);
                }
                let iv: &[u8; 12] = combined[..12].try_into().map_err(|_| Error::Crypto)?;
                // Exact MetadataEncryptor: every first12 bytes are IV, even OM.
                // Never attempt a native framed candidate or unauthenticated fallback.
                {
                    let result = port.decrypt(iv, &combined[12..]).await;
                    self.current()?;
                    self.release(result?)
                }
            }
        }
    }
    pub async fn decrypt_text(&self, ciphertext: &str) -> Result<String> {
        let bytes = self.decrypt_bytes(ciphertext).await?;
        let mut output = String::from_utf8_lossy(&bytes).into_owned();
        if let Err(error) = self.current() {
            output.zeroize();
            return Err(error);
        }
        Ok(output)
    }
}
// Source-matches cryptoService.base64ToUint8Array: URL alphabet mapping and
// padding precede browser atob's forgiving ASCII-whitespace/trailing-bit decode.
fn decode_browser_base64(input: &str) -> Result<Vec<u8>> {
    if input.is_empty() {
        return Err(Error::Crypto);
    }
    let mut normalized = input.replace('-', "+").replace('_', "/");
    let remainder = normalized.len() % 4;
    if remainder != 0 {
        normalized.extend(std::iter::repeat_n('=', 4 - remainder));
    }
    normalized.retain(|value| !matches!(value, '\t' | '\n' | '\u{000c}' | '\r' | ' '));
    if normalized.len() % 4 == 0 {
        if normalized.ends_with("==") {
            normalized.truncate(normalized.len() - 2);
        } else if normalized.ends_with('=') {
            normalized.pop();
        }
    }
    if normalized.len() % 4 == 1
        || normalized
            .bytes()
            .any(|value| !value.is_ascii_alphanumeric() && value != b'+' && value != b'/')
    {
        return Err(Error::Crypto);
    }
    let remainder = normalized.len() % 4;
    if remainder != 0 {
        normalized.extend(std::iter::repeat_n('=', 4 - remainder));
    }
    let engine = base64::engine::GeneralPurpose::new(
        &base64::alphabet::STANDARD,
        base64::engine::GeneralPurposeConfig::new().with_decode_allow_trailing_bits(true),
    );
    engine.decode(normalized).map_err(|_| Error::Crypto)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "master_tests.rs"]
mod tests;
