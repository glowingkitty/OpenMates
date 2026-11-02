//! Post-validation original-owned socket admission only. No new authority or IO.
use super::*;
impl Client {
    pub(in crate::client) fn check_active_owned_socket_start(&self) -> Result<()> {
        if let Some(original) = self.active_owned_operation.as_ref() {
            original.check_client(self, false)?;
            original.check_initial_credentials(self, false)?;
        }
        Ok(())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "transport_owned_start_tests.rs"]
mod tests;
