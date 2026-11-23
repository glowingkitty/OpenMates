//! Work-layer authority of the cookie client on every shell (shared core).
//!
//! `work::Backend::Cookie` (Projects, commits, timeline) first ran only on the
//! native CLI/Apple session. In the web Worker the admitted client holds
//! browser credentials and a non-extractable WebCrypto master instead, so the
//! request gate accepts either authority and master-wrapped keys (Project and
//! Team key wrappers) are unwrapped through the master binding, never by
//! extracting the master. Spec: feature.projects `projects.history.native-commits`.
use super::credentials::MasterBinding;
use super::*;

impl Client {
    /// Request authority of the work layer: the native session, or the
    /// admitted browser credentials of the web Worker (cookie transport, which
    /// keeps its own owner and generation fences).
    ///
    /// # Errors
    /// `Authentication` without credentials, `Expired` for an expired paired
    /// session, `Protocol` when both authorities are present.
    pub(crate) fn require_work_authority(&self) -> Result<()> {
        if self.browser_credentials.is_some() && self.browser_cookies() {
            return self.require_credentials().map(|_| ());
        }
        self.require_session().map(|_| ())
    }

    /// Unwraps a 32-byte key wrapped under the master key. Native material keeps
    /// `crypto::decrypt_bytes` (framed and legacy formats); the browser binding
    /// decrypts the IV-first web format inside WebCrypto. The binding is checked
    /// again after the await so a sign-out or account switch meanwhile cancels.
    ///
    /// # Errors
    /// `Crypto` when the wrapper does not authenticate or is not 32 bytes;
    /// `Cancelled` when the credentials changed during the unwrap.
    pub(crate) async fn work_unwrap_with_master(&self, ciphertext: &str) -> Result<Key> {
        let binding = self.master_binding()?;
        let plain = match &binding {
            MasterBinding::Native(key) => crypto::decrypt_bytes(ciphertext, key)?,
            MasterBinding::Browser(master) => master.decrypt_bytes(ciphertext).await?,
        };
        binding.check(self)?;
        let bytes: [u8; 32] = plain.as_slice().try_into().map_err(|_| Error::Crypto)?;
        Ok(zeroize::Zeroizing::new(bytes))
    }
    /// Wraps a fresh 32-byte object key under the master key in the server
    /// wrapper format (IV || ciphertext || tag, empty AAD) that web and native
    /// readers accept. The browser binding encrypts inside WebCrypto, so the
    /// web Worker's non-extractable master works; checked again after the await.
    ///
    /// # Errors
    /// `Crypto` on an encryption failure; `Cancelled` when the credentials
    /// changed during the wrap.
    pub(crate) async fn work_wrap_with_master(&self, plaintext: &[u8]) -> Result<String> {
        let binding = self.master_binding()?;
        let wrapped = match &binding {
            MasterBinding::Native(key) => {
                crypto::server_fields::encrypt_bytes(plaintext, key, &[])?
            }
            MasterBinding::Browser(master) => master.encrypt_server_bytes(plaintext).await?,
        };
        binding.check(self)?;
        Ok(wrapped)
    }

    /// The master key bytes for the private slug lookup index, when this shell
    /// holds them. The web Worker's master is non-extractable, so it gets
    /// `None` and creates Projects without a slug, like the web's own create.
    ///
    /// # Errors
    /// `Authentication`/`Expired` without credentials.
    pub(crate) fn work_slug_lookup_master(&self) -> Result<Option<Key>> {
        Ok(match self.master_binding()? {
            MasterBinding::Native(key) => Some(key),
            MasterBinding::Browser(_) => None,
        })
    }
}
