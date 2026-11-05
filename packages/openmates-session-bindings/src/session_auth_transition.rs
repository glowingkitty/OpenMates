//! Original native invocation sequencing, not authentication authority or protocol.
use super::*;
use zeroize::Zeroize;

#[derive(Default)]
pub(super) struct IdentityTransitions { pending: Option<u64>, draining: usize }
#[derive(Clone)]
struct Transition { state: Arc<State>, epoch: u64, _lifetime: Arc<PendingLifetime> }
struct PendingLifetime { state:Arc<State>, epoch:u64 }
// A started detached driver can still merge credentials or mutate the Client
// after a newer preparation is dropped. This independent negative owns its REAL
// task lifetime; it neither matches nor clears any pending preparation epoch.
struct DriverDrain { state: Arc<State> }
impl Drop for DriverDrain {
    fn drop(&mut self) {
        if let Ok(mut transitions) = self.state.identity_transitions.lock() {
            transitions.draining = transitions.draining.checked_sub(1)
                .expect("original auth driver drain count");
        }
    }
}
impl Transition {
    fn check_locked(&self, transitions: &IdentityTransitions) -> Result<()> {
        if self.state.closed.load(Ordering::Acquire)
            || self.state.identity_epoch.load(Ordering::Acquire) != self.epoch
            || transitions.pending != Some(self.epoch) {
            return Err(Error::Cancelled.into());
        }
        Ok(())
    }
    fn check(&self) -> Result<()> {
        let transitions = self.state.identity_transitions.lock().map_err(|_| BindingError::from(Error::Protocol))?;
        self.check_locked(&transitions)
    }
    fn start_driver(&self) -> Result<DriverDrain> {
        let mut transitions = self.state.identity_transitions.lock().map_err(|_| BindingError::from(Error::Protocol))?;
        self.check_locked(&transitions)?;
        transitions.draining = transitions.draining.checked_add(1).ok_or_else(|| BindingError::from(Error::Conflict))?;
        Ok(DriverDrain { state: self.state.clone() })
    }
}
impl Drop for PendingLifetime {
    fn drop(&mut self) {
        if let Ok(mut transitions) = self.state.identity_transitions.lock() {
            // Late/abandoned A can never clear the pending state of B.
            if transitions.pending == Some(self.epoch) { transitions.pending = None; }
        }
    }
}
struct SecretInput {
    value: Zeroizing<String>,
    #[cfg(test)] probe: Option<Arc<Mutex<Vec<bool>>>>,
}
impl SecretInput { fn new(value:String)->Self { Self { value:Zeroizing::new(value), #[cfg(test)] probe:None } } }
impl Drop for SecretInput { fn drop(&mut self) {
    self.value.zeroize();
    #[cfg(test)] if let Some(probe)=&self.probe { probe.lock().expect("private scratch probe").push(self.value.is_empty()); }
} }
enum Action {
    Import(Session),
    Password { email:SecretInput, password:SecretInput, tfa:Option<SecretInput>, options:openmates_sdk::PasswordLoginOptions },
    Team(Option<String>),
    Logout,
}
pub(crate) struct PreparedAuth { transition:Transition, action:Action }
impl PreparedAuth {
    async fn drive(self) -> Result<Zeroizing<String>> {
        let Self { transition, action } = self;
        transition.check()?;
        let driver=transition.state.clone();
        let driver_transition=transition.clone();
        // Keep the transition owner on the caller side through the detached join.
        // The actual admitted Core operation is always awaited to completion.
        let joined=tokio::spawn(async move {
            // Only this actually started task acquires the drain negative.
            // Declared BEFORE the Client guard so Client/operation cleanup drops
            // first. No identity mutex is retained across this or any await.
            let _drain=driver_transition.start_driver()?;
            SessionBridge::drain_saved_driver(&driver).await?;
            let _legacy_lane=driver.legacy_client_lane.lock().await;
            let mut client=driver.client.lock().await;
            driver_transition.check()?;
            let output=match action {
                Action::Import(session) => {
                    client.reset(&driver.endpoint,Some(session)).map_err(BindingError::from)?;
                    Zeroizing::new(String::new())
                }
                Action::Password { email,password,tfa,options } => {
                    client.login_password_with_options(&email.value,&password.value,tfa.as_ref().map(|v|v.value.as_str()),options)
                        .await.map_err(BindingError::from)?;
                    Zeroizing::new(serde_json::to_string(client.user()).map_err(|_| BindingError::from(Error::Protocol))?)
                }
                Action::Team(id) => {
                    client.set_team(id.as_deref()).map_err(BindingError::from)?;
                    Zeroizing::new(String::new())
                }
                Action::Logout => {
                    client.logout().await.map_err(BindingError::from)?;
                    Zeroizing::new(String::new())
                }
            };
            driver_transition.check()?;
            Ok::<_,BindingError>(output)
        }).await.map_err(|_| BindingError::from(Error::Protocol));
        // Mask obsolete errors too, including a detached task join failure.
        transition.check()?;
        joined?
    }
    pub(crate) async fn run_unit(self)->Result<()> { self.drive().await.map(|_|()) }
    pub(crate) async fn run_string(self)->Result<String> {
        let mut output=self.drive().await?;
        Ok(std::mem::take(&mut *output))
    }
}
pub(crate) struct PreparedClose { transition:Transition }
impl PreparedClose {
    pub(crate) async fn run(self)->Result<()> {
        let state=self.transition.state.clone();
        // Terminal cleanup is never suppressed by an identity epoch comparison.
        // Like the original close, it awaits the real serialized Client drain.
        tokio::spawn(async move {
            SessionBridge::drain_saved_driver(&state).await?;
            let _legacy_lane=state.legacy_client_lane.lock().await;
            state.client.lock().await.forget_session();
            Ok::<_,BindingError>(())
        })
            .await.map_err(|_| BindingError::from(Error::Protocol))??;
        Ok(())
    }
}
impl SessionBridge {
    // Held only for synchronous entry/admission bookkeeping, never across await.
    pub(super) fn identity_admission(&self)->Result<std::sync::MutexGuard<'_,IdentityTransitions>> {
        let transitions=self.state.identity_transitions.lock().map_err(|_|BindingError::from(Error::Protocol))?;
        if self.state.closed.load(Ordering::Acquire) { return Err(Error::Cancelled.into()); }
        if transitions.pending.is_some() || transitions.draining != 0 { return Err(Error::Conflict.into()); }
        Ok(transitions)
    }
    fn reserve_identity_transition(&self,terminal:bool)->Result<Transition> {
        let mut transitions=self.state.identity_transitions.lock().map_err(|_|BindingError::from(Error::Protocol))?;
        if self.state.closed.load(Ordering::Acquire) && !terminal { return Err(Error::Cancelled.into()); }
        // This is only retirement. It never claims that authentication changed.
        let epoch=self.state.identity_epoch.fetch_add(1,Ordering::AcqRel).wrapping_add(1);
        transitions.pending=Some(epoch);
        let transition=Transition {state:self.state.clone(),epoch,_lifetime:Arc::new(PendingLifetime {state:self.state.clone(),epoch})};
        let cancelled=self.cancel();
        drop(transitions);
        cancelled?;
        Ok(transition)
    }
    pub(crate) fn prepare_import_session(&self,session_json:String)->Result<PreparedAuth> {
        let encoded=SecretInput::new(session_json);
        // Malformed replacement still retires all earlier identity scopes.
        let transition=self.reserve_identity_transition(false)?;
        if encoded.value.len()>1024*1024 { return Err(Error::Invalid("session").into()); }
        let session:Session=serde_json::from_str(&encoded.value).map_err(|_|BindingError::from(Error::Invalid("session")))?;
        Ok(PreparedAuth {transition,action:Action::Import(session)})
    }
    pub(crate) fn prepare_login_password(&self,email:String,password:String,tfa:Option<String>,options:openmates_sdk::PasswordLoginOptions)->Result<PreparedAuth> {
        let action=Action::Password {email:SecretInput::new(email),password:SecretInput::new(password),tfa:tfa.map(SecretInput::new),options};
        let transition=self.reserve_identity_transition(false)?;
        Ok(PreparedAuth {transition,action})
    }
    pub(crate) fn prepare_set_team(&self,id:Option<String>)->Result<PreparedAuth> {
        let transition=self.reserve_identity_transition(false)?;
        Ok(PreparedAuth {transition,action:Action::Team(id)})
    }
    pub(crate) fn prepare_logout(&self)->Result<PreparedAuth> {
        let transition=self.reserve_identity_transition(false)?;
        Ok(PreparedAuth {transition,action:Action::Logout})
    }
    pub(crate) fn prepare_close(&self)->Result<PreparedClose> {
        self.state.closed.store(true,Ordering::Release);
        let transition=self.reserve_identity_transition(true)?;
        Ok(PreparedClose {transition})
    }
}
#[cfg(test)]
#[path="session_auth_transition_tests.rs"]
mod tests;
