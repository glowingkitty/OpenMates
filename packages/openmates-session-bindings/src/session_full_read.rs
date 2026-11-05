//! Full JSON reads retain their original authority until actual runtime allocation.
use super::work::{WorkGuard, work_authority};
use super::*;
use openmates_sdk::client::full_chat_read::FullChatReadAdmission;
use zeroize::Zeroize;

// Opaque, one-shot, no plaintext getter or Clone/Debug/Serialize implementation.
// The native runtime wrapper may cross a scheduler queue, never an authority.
pub(crate) struct FullChatOutput {
    state: Arc<State>,
    guard: Arc<WorkGuard>,
    admission: FullChatReadAdmission,
    output: Zeroizing<String>,
}
impl FullChatOutput {
    fn check_original(&self, client: &Client) -> Result<()> {
        work_authority(&self.guard)
            .and_then(|_| self.admission.check(client).map_err(BindingError::from))
            .and_then(|_| work_authority(&self.guard))
    }
    fn encode_original<T>(&mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        work_authority(&self.guard)?;
        let state = self.state.clone();
        // Sync event-loop/GIL release must never block behind another operation.
        let mut client = SessionBridge::try_live_client(&state)?;
        self.check_original(&client)?;
        let value = encode(&self.output)?;
        // Revocation during native allocation refuses handoff. Foreign allocation
        // erasure is not promised; the owned Rust scratch is always wiped.
        self.check_original(&client)?;
        client.set_operation_cancel(CancellationToken::new());
        work_authority(&self.guard)?;
        Ok(value)
    }
    pub(crate) fn encode_with<T>(mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        self.encode_checked(encode)
    }
    fn encode_checked<T>(&mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        let result = self.encode_original(encode);
        self.output.zeroize();
        result
    }
    pub(crate) fn release_json(self) -> Result<String> {
        let mut value = self.encode_with(|text| Ok(Zeroizing::new(text.to_owned())))?;
        Ok(std::mem::take(&mut *value))
    }
}
impl Drop for FullChatOutput {
    fn drop(&mut self) {
        // Cancels only the original A child, never the client's current B child.
        self.guard.cancel();
    }
}
impl SessionBridge {
    pub(crate) async fn full_chat_read_prepare(&self, id: String) -> Result<FullChatOutput> {
        let guard = Arc::new(self.admit_work()?);
        self.full_chat_read_prepare_admitted(id, guard).await
    }
    async fn full_chat_read_prepare_admitted(&self, id: String, guard: Arc<work::WorkGuard>) -> Result<FullChatOutput> {
        work::work_authority(&guard)?;
        let transaction_guard = guard.clone();
        let state = self.state.clone();
        let output_state = state.clone();
        let joined = self.transaction(async move {
            let guard = transaction_guard;
            let mut client = Self::live_client(&state).await?;
            work_authority(&guard)?;
            client.set_operation_cancel(guard.token());
            // Captures owner/key/request/epoch/source/privacy/gate before HTTP.
            // This exact admission crosses both Rust and foreign runtime queues.
            let (read, admission) = client.open_chat_with_metadata_and_admission(&id)
                .await.map_err(BindingError::from)?;
            let output = Zeroizing::new(serde_json::to_string(&read)
                .map_err(|_| BindingError::from(Error::Protocol))?);
            admission.check(&client).map_err(BindingError::from)?;
            work_authority(&guard)?;
            Ok(FullChatOutput {state: output_state, guard, admission, output})
        }).await;
        if joined.is_err() { guard.cancel(); }
        joined
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_full_chat_read_prepare(&self, id: String) -> impl Future<Output = Result<FullChatOutput>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.full_chat_read_prepare_admitted(std::mem::take(&mut *id), guard).await
        }
    }

}

#[cfg(test)]
#[path = "session_full_read_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "session_full_read_post_gate_tests.rs"]
mod post_gate_tests;
