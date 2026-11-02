//! Rich saved-chat JSON remains sealed until actual Rust/JS/Python allocation.
use super::work::{WorkGuard, work_authority};
use super::*;
use openmates_sdk::client::{chat_details::ChatDetailsOptions, full_chat_read::FullChatReadAdmission};
use zeroize::Zeroize;

// One-shot original scope, no Clone/Debug/Serialize or plaintext getter.
pub(crate) struct ChatDetailsOutput {
    state: Arc<State>,
    guard: Arc<WorkGuard>,
    admission: FullChatReadAdmission,
    original_privacy: PrivacyOptions,
    original_gate: Option<Arc<dyn Fn() -> openmates_sdk::Result<()> + Send + Sync>>,
    output: Zeroizing<String>,
}
impl ChatDetailsOutput {
    fn check_original(&self, client: &Client) -> Result<()> {
        self.original_privacy.verify().map_err(BindingError::from)?;
        if let Some(gate) = &self.original_gate {gate().map_err(BindingError::from)?;}
        work_authority(&self.guard)?;
        self.admission.check(client).map_err(BindingError::from)?;
        work_authority(&self.guard)
    }
    fn encode_original<T>(&mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        work_authority(&self.guard)?;
        let state = self.state.clone();
        // Never block the event loop/GIL behind another operation's async lock.
        let mut client = SessionBridge::try_live_client(&state)?;
        self.check_original(&client)?;
        let value = encode(&self.output)?;
        // Refuse after allocation if the original policy/token was retired.
        // Owned Rust scratch is wiped; foreign heap erasure is not promised.
        self.check_original(&client)?;
        client.set_operation_cancel(CancellationToken::new());
        work_authority(&self.guard)?;
        Ok(value)
    }
    fn encode_checked<T>(&mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        let result = self.encode_original(encode);
        self.output.zeroize();
        result
    }
    pub(crate) fn encode_with<T>(mut self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        self.encode_checked(encode)
    }
    fn release_json(self) -> Result<String> {
        let mut value = self.encode_with(|text| Ok(Zeroizing::new(text.to_owned())))?;
        Ok(std::mem::take(&mut *value))
    }
}
impl Drop for ChatDetailsOutput {
    fn drop(&mut self) {self.guard.cancel();} // Only A, never the current B child.
}
impl SessionBridge {
    /// Explicit SessionBridge credentials, same rich core operation as native.
    pub async fn chat_details(&self, id: String, options_json: String) -> Result<String> {
        self.chat_details_prepare(id, options_json).await?.release_json()
    }
    pub(crate) async fn chat_details_prepare(&self, id: String, options_json: String) -> Result<ChatDetailsOutput> {
        let guard = Arc::new(self.admit_work()?);
        self.chat_details_prepare_admitted(id, options_json, guard).await
    }
    async fn chat_details_prepare_admitted(&self, id: String, options_json: String, guard: Arc<work::WorkGuard>) -> Result<ChatDetailsOutput> {
        work::work_authority(&guard)?;
        if options_json.len() > 4096 {
            return Err(Error::Invalid("Chat details options exceed the supported size.").into());
        }
        let input: Value = serde_json::from_str(&options_json)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid chat details options.")))?;
        if !input.is_object() {return Err(Error::Invalid("Invalid chat details options.").into());}
        let options: ChatDetailsOptions = serde_json::from_value(input)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid chat details options.")))?;
        let transaction_guard = guard.clone();
        let state = self.state.clone();
        let output_state = state.clone();
        let joined = self.transaction(async move {
            let guard = transaction_guard;
            let mut client = Self::live_client(&state).await?;
            work_authority(&guard)?;
            client.set_operation_cancel(guard.token());
            // Original bridge policy is captured ONCE before actual core IO.
            let original_privacy = client.options().privacy.clone();
            let original_gate = client.options().private_operation_gate.clone();
            let mut read = match client.read_chat_details(&id, options).await {
                Ok(read) => read,
                Err(error) => {
                    // Still holding A's client lane; B cannot have installed yet.
                    client.set_operation_cancel(CancellationToken::new());
                    return Err(BindingError::from(error));
                }
            };
            read.check(&client).map_err(BindingError::from)?;
            let output = Zeroizing::new(read.sdk_json().map_err(BindingError::from)?);
            // Move the exact admission from the actual read; never mint a fresh
            // post-IO saved/full-read admission or select plaintext in a facade.
            let admission = read.take_admission(&client).map_err(BindingError::from)?;
            admission.check(&client).map_err(BindingError::from)?;
            work_authority(&guard)?;
            Ok(ChatDetailsOutput {state:output_state,guard,admission,original_privacy,original_gate,output})
        }).await;
        if joined.is_err() {guard.cancel();}
        joined
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_chat_details_prepare(&self, id: String, options_json: String) -> impl Future<Output = Result<ChatDetailsOutput>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let mut options_json = Zeroizing::new(options_json);
        let original = self.admit_work().map(Arc::new);
        let bridge = self.clone();
        async move {
            let guard = original?;
            work::work_authority(&guard)?;
            bridge.chat_details_prepare_admitted(std::mem::take(&mut *id), std::mem::take(&mut *options_json), guard).await
        }
    }

}
#[cfg(test)]
#[path = "session_chat_details_tests.rs"]
mod tests;
