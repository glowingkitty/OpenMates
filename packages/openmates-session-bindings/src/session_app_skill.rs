//! Temporary direct Apps execution; shared core owns request/polling semantics.
use super::work::{WorkGuard, work_authority};
use super::*;
use openmates_sdk::client::DirectAppSkillAdmission;
use zeroize::Zeroize;

struct Pending(Value);
impl Drop for Pending {
    fn drop(&mut self) {
        super::embed_versions::wipe(&mut self.0);
    }
}
fn original_policy(
    guard: &WorkGuard,
    privacy: &PrivacyOptions,
    gate: &Option<Arc<dyn Fn() -> openmates_sdk::Result<()> + Send + Sync>>,
) -> Result<()> {
    work_authority(guard)?;
    privacy.verify().map_err(BindingError::from)?;
    if let Some(gate) = gate {
        gate().map_err(BindingError::from)?;
    }
    work_authority(guard)
}
/// No Clone/Debug/serde/plaintext getter: exact pre-skill admission crosses queues.
pub(crate) struct DirectSkillOutput {
    state: Arc<State>,
    guard: Arc<WorkGuard>,
    admission: DirectAppSkillAdmission,
    original_privacy: PrivacyOptions,
    original_gate: Option<Arc<dyn Fn() -> openmates_sdk::Result<()> + Send + Sync>>,
    output: Zeroizing<String>,
}
impl DirectSkillOutput {
    fn check_original(&self, client: &Client) -> Result<()> {
        original_policy(&self.guard, &self.original_privacy, &self.original_gate)?;
        self.admission.check(client).map_err(BindingError::from)?;
        original_policy(&self.guard, &self.original_privacy, &self.original_gate)?;
        // The final successful caller callback may itself retire original core
        // authority. No callback follows this restrictive original recheck.
        self.admission.check_after_private_gate(client).map_err(BindingError::from)
    }
    fn encode_original<T>(&self, encode: impl FnOnce(&str) -> Result<T>) -> Result<T> {
        original_policy(&self.guard, &self.original_privacy, &self.original_gate)?;
        let mut client = SessionBridge::try_live_client(&self.state)?;
        self.check_original(&client)?;
        let value = encode(&self.output)?;
        self.check_original(&client)?;
        // Exact A still owns this locked completed lane. A stale A never resets B.
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
impl Drop for DirectSkillOutput {
    fn drop(&mut self) {
        self.guard.cancel();
    }
}
const MAX_DIRECT_SKILL_INPUT_BYTES: usize = 1024 * 1024;

// Own queued plaintext before any foreign scheduling. The test-only witness
// records only whether this application-owned buffer was explicitly zeroized.
struct QueuedDirectSkillInput {
    encoded: Zeroizing<String>,
    #[cfg(test)]
    wiped_on_drop: Option<Arc<AtomicBool>>,
}
impl QueuedDirectSkillInput {
    fn new(encoded: String) -> Self {
        Self {
            encoded: Zeroizing::new(encoded),
            #[cfg(test)]
            wiped_on_drop: None,
        }
    }
}
impl Drop for QueuedDirectSkillInput {
    fn drop(&mut self) {
        self.encoded.zeroize();
        #[cfg(test)]
        if let Some(witness) = &self.wiped_on_drop {
            witness.store(self.encoded.is_empty(), Ordering::Release);
        }
    }
}
// Exact original admission and input travel together. No replacement admission
// is minted when a native scheduler eventually polls this owned call.
struct QueuedDirectSkill {
    bridge: SessionBridge,
    guard: Arc<WorkGuard>,
    app: String,
    skill: String,
    input_json: QueuedDirectSkillInput,
}
impl QueuedDirectSkill {
    async fn run(self) -> Result<DirectSkillOutput> {
        let Self { bridge, guard, app, skill, input_json } = self;
        work_authority(&guard)?;
        let input = Pending(
            serde_json::from_str(&input_json.encoded)
                .map_err(|_| BindingError::from(Error::Invalid("Invalid App input JSON.")))?,
        );
        drop(input_json);
        work_authority(&guard)?;
        let transaction_guard = guard.clone();
        let state = bridge.state.clone();
        let output_state = state.clone();
        let result = bridge
            .transaction(async move {
                let guard = transaction_guard;
                let mut input = input;
                let mut client = SessionBridge::live_client(&state).await?;
                work_authority(&guard)?;
                client.set_operation_cancel(guard.token());
                // Capture policy/identity before the initial real auth observation.
                let original_privacy = client.options().privacy.clone();
                let original_gate = client.options().private_operation_gate.clone();
                original_policy(&guard, &original_privacy, &original_gate)?;
                let observed_owner = client
                    .user()
                    .get("id")
                    .and_then(Value::as_str)
                    .filter(|v| !v.is_empty())
                    .or_else(|| {
                        client
                            .user()
                            .get("user_id")
                            .and_then(Value::as_str)
                            .filter(|v| !v.is_empty())
                    });
                if observed_owner.is_none() {
                    let validated = client.validate_session().await;
                    original_policy(&guard, &original_privacy, &original_gate)?;
                    validated.map_err(BindingError::from)?;
                }
                original_policy(&guard, &original_privacy, &original_gate)?;
                // Capture ONCE after genuine owner observation, before skill HTTP.
                let admission = client
                    .direct_app_skill_admission()
                    .map_err(BindingError::from)?;
                admission.check(&client).map_err(BindingError::from)?;
                let result = client
                    .run_direct_app_skill(&app, &skill, std::mem::take(&mut input.0))
                    .await
                    .map(Pending);
                // Pre-auth/operation errors are fixed typed metadata, no server text.
                original_policy(&guard, &original_privacy, &original_gate)?;
                let result = result.map_err(BindingError::from)?;
                admission.check(&client).map_err(BindingError::from)?;
                let output = Zeroizing::new(
                    serde_json::to_string(&result.0)
                        .map_err(|_| BindingError::from(Error::Protocol))?,
                );
                admission.check(&client).map_err(BindingError::from)?;
                original_policy(&guard, &original_privacy, &original_gate)?;
                Ok(DirectSkillOutput {
                    state: output_state,
                    guard,
                    admission,
                    original_privacy,
                    original_gate,
                    output,
                })
            })
            .await;
        if result.is_err() {
            guard.cancel();
        }
        result
    }
}
impl SessionBridge {
    fn capture_direct_skill(
        &self,
        app: String,
        skill: String,
        input_json: String,
    ) -> Result<QueuedDirectSkill> {
        let input_json = QueuedDirectSkillInput::new(input_json);
        if input_json.encoded.len() > MAX_DIRECT_SKILL_INPUT_BYTES {
            return Err(Error::Invalid("App input exceeds the supported limit.").into());
        }
        let guard = Arc::new(self.admit_work()?);
        Ok(QueuedDirectSkill { bridge: self.clone(), guard, app, skill, input_json })
    }
    /// Temporary structured result; never auto-downloads files or saves Apps history.
    /// Original work is admitted synchronously before returning this owned future.
    pub fn run_skill(
        &self,
        app: String,
        skill: String,
        input_json: String,
    ) -> impl Future<Output = Result<String>> + Send + 'static {
        let prepared = self.run_skill_prepare(app, skill, input_json);
        async move { prepared.await?.release_json() }
    }
    // Synchronous factory: cancellation between creation and first poll reaches
    // the registered ORIGINAL WorkGuard, including all foreign scheduling gaps.
    pub(crate) fn run_skill_prepare(
        &self,
        app: String,
        skill: String,
        input_json: String,
    ) -> impl Future<Output = Result<DirectSkillOutput>> + Send + 'static {
        let prepared = self.capture_direct_skill(app, skill, input_json);
        async move { prepared?.run().await }
    }
}
#[cfg(test)]
#[path = "session_app_skill_tests.rs"]
mod tests;
