//! Command lifecycle and interactive profiles belong to the application.
use openmates::{
    cli::{self, CliError, CliOutput, GlobalArgs, Invocation},
    client::{Client, ClientOptions},
    error::Error,
    privacy,
    profile::{self, ProfileEnvironment, ProfileOptions},
    runtime_store::RuntimeStore,
    server, session_runtime,
    storage::StorageMode,
};
use serde_json::json;
use std::{
    collections::BTreeMap,
    io::{self, IsTerminal, Write},
    path::PathBuf,
    time::Duration,
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

#[path = "list_stage_diagnostic.rs"]
mod list_stage_diagnostic;
use list_stage_diagnostic::{ListStages, Stage};

pub async fn run(globals: GlobalArgs, invocation: Invocation) -> Result<CliOutput, CliError> {
    let stages = ListStages::capture(invocation.command_path() == "chats list");
    let result = run_with_list_stages(globals, invocation, &stages).await;
    stages.finish(result.is_ok());
    stages.emit();
    result
}

async fn run_with_list_stages(
    globals: GlobalArgs,
    invocation: Invocation,
    stages: &ListStages,
) -> Result<CliOutput, CliError> {
    let policy = cli::trusted_account::check_environment(
        &globals,
        Some(&invocation),
        &cli::trusted_account::Environment::capture(),
    )?;
    // Local help and known migration gaps never unlock or read an account.
    if let Some(result) = cli::execute_public(&invocation) {
        return result;
    }
    cli::validate_application_saved_read(&invocation)?;
    if cli::docs::is_public(&invocation)
        || matches!(
            invocation.command_path().as_str(),
            "settings developers devices" | "settings security sessions"
        )
    {
        let cancel = CancellationToken::new();
        let _signals = SignalGuard::new(cancel.clone())?;
        let directories = directories::BaseDirs::new().ok_or(Error::Io)?;
        let mut client = public_client(
            &globals,
            ProfileEnvironment::capture(),
            directories.home_dir(),
            std::env::var("OPENMATES_APP_URL")
                .ok()
                .filter(|s| !s.is_empty()),
        )?;
        if let Some(result) = cli::web_only_account(&invocation, &client.application_url()) {
            return result;
        }
        return cancellable(
            cli::docs::execute(&invocation, &mut client, cancel.clone()),
            &cancel,
            Duration::from_secs(2),
        )
        .await;
    }
    let api_key = globals.api_key.or_else(|| {
        std::env::var("OPENMATES_API_KEY")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(Zeroizing::new)
    });
    if cli::embed_user_edit_supported(&invocation) && api_key.is_some() {
        return Err(CliError::Unsupported{command:invocation.command_path(),reason:"Embed versions made by the user (Enhance, restore) need a signed-in Personal session; API keys cannot save them.".into()});
    }
    if invocation.command_path()=="embeds share" && api_key.is_some() {
        return Err(CliError::Unsupported{command:invocation.command_path(),reason:"Personal Cookie embed sharing never substitutes an API key or opens a Cookie profile for it.".into()});
    }
    // Explicit key-only embed slice: reject before resolving/opening any Cookie
    // or Team profile. SDK coverage does not establish Cookie auth parity.
    if cli::sdk_embeds_supported(&invocation) && !matches!(invocation.command_path().as_str(), "embeds versions show" | "embeds test-result") && api_key.is_none() {
        return Err(CliError::Unsupported { command: invocation.command_path(), reason: "This native embed slice requires an explicit API key; Cookie and Team embed parity remain required and no profile was loaded.".into() });
    }
    let cancel = CancellationToken::new();
    let _signals = SignalGuard::new(cancel.clone())?;
    let logout = invocation.command_path() == "logout";
    if logout && api_key.is_some() {
        return Err(CliError::Invalid("API keys are explicitly revoked through API-key management; session logout cannot revoke a key.".into()));
    }
    let server_command = invocation.path.first().is_some_and(|name| name == "server");
    let directories = directories::BaseDirs::new().ok_or(Error::Io)?;
    let mut environment = ProfileEnvironment::capture();
    if logout {
        environment.api_url = None;
    }
    let server_account = server_command.then(|| ProfileOptions {
        profile: environment.profile.clone(),
        state_dir: globals
            .state_dir
            .clone()
            .or_else(|| environment.state_dir.clone()),
        api_url: globals
            .api_url
            .clone()
            .or_else(|| environment.api_url.clone()),
    });
    // The legacy server --profile selects the Compose deployment profile, not
    // an account. Host administration does not load authentication; an explicitly
    // requested paid quick test unlocks the selected native state separately.
    if server_command {
        environment.profile = None;
    }
    let resolved = profile::resolve(
        ProfileOptions {
            profile: if server_command {
                None
            } else {
                globals.profile
            },
            state_dir: globals.state_dir,
            api_url: if logout { None } else { globals.api_url },
        },
        environment,
        directories.home_dir(),
    )?;
    if logout {
        // Local revocation never needs a keyring/vault unlock or a valid current
        // target override. Remote logout uses only safely loaded original-origin
        // credentials; unavailable credentials cannot block local cleanup.
        cli::private_path::preflight(&resolved.state_dir)?;
        let store = RuntimeStore::new(Some(resolved.state_dir.clone()), globals.encrypted_vault)
            .await
            .map_err(|error| cli::private_path::explain(&resolved.state_dir, error))?;
        return logout_native(&store, globals.json).await;
    }
    if server_command {
        return run_server(
            &invocation,
            ServerContext {
                profile: resolved,
                account: server_account.expect("server account options"),
                home: directories.home_dir().to_path_buf(),
                encrypted_vault: globals.encrypted_vault,
                json_output: globals.json,
                api_key_selected: api_key.is_some(),
                trusted_guard: policy.enabled,
            },
            &cancel,
        )
        .await;
    }
    let trusted_path = cli::trusted_account::enforced_profile(&resolved.state_dir, policy.enabled)?;
    if let Some(api_key) = api_key {
        // Chat-scoped work aliases use the same explicit-key namespaces and
        // validation as their canonical Tasks/Plans commands, without loading
        // any Cookie profile or granting an additional SDK capability.
        let normalized = cli::normalize_chat_work(&invocation)?;
        let invocation = normalized.as_ref().unwrap_or(&invocation);
        let key_account = cli::sdk_key_account_supported(invocation);
        let key_command = cli::sdk_key_command_supported(invocation);
        if !key_account && !key_command && invocation.command_path() != "apps code get_docs" && invocation.path.first().is_none_or(|name| {
            !matches!(
                name.as_str(),
                "tasks" | "plans" | "projects" | "workflows" | "history" | "drafts" | "embeds"
            )
        }) {
            return Err(CliError::Unsupported{command:invocation.command_path(),reason:"This native API-key command route is not implemented yet; session credentials were not loaded or mixed with the key.".into()});
        }
        let installed = server::installed_api(&resolved.state_dir)?;
        let api = resolved.api_url(None, installed.as_deref())?;
        let credentials = openmates_sdk::sdk::ApiKey::new(&api_key)?;
        let store = RuntimeStore::new(
            Some(profile::api_key_state_dir(
                &resolved.state_dir,
                &api,
                &api_key,
            )),
            false,
        )
        .await?;
        let device_id = store.device_identity().await?;
        let draft_private_gate = privacy::gate_for_profile(&resolved, directories.home_dir());
        let mut sdk = openmates_sdk::sdk::OpenMates::new(openmates_sdk::sdk::SdkOptions {
            api_url: api.clone(),
            credentials: openmates_sdk::sdk::SdkCredentials::ApiKey(credentials),
            device_id,
            client_options: ClientOptions {
                identity: openmates_sdk::ClientIdentity::Cli,
                private_operation_gate: Some(draft_private_gate.clone()),
                ..Default::default()
            },
        })?;
        sdk.set_operation_cancel(cancel.clone());
        if policy.protected || trusted_path.is_some() {
            let expected = cli::trusted_account::load(&resolved.state_dir)?;
            let identity = cancellable(
                async { sdk.sdk_session().await.map_err(CliError::from) },
                &cancel,
                Duration::from_secs(2),
            )
            .await?;
            cli::trusted_account::verify(expected.as_deref(), &identity["user"])?;
        }
        let result = cancellable(
            async {
                if key_account {
                    return cli::execute_sdk_account(invocation, &mut sdk, cancel.clone()).await;
                }
                if key_command {
                    return cli::execute_sdk_key_command(invocation, &mut sdk).await;
                }
                match invocation.path.first().map(String::as_str) {
                    Some("apps") => {
                        cli::execute_sdk_apps(invocation, &mut sdk, cancel.clone()).await
                    }
                    Some("embeds") => {
                        cli::execute_sdk_embeds_with_gate(invocation, &mut sdk, cancel.clone(), draft_private_gate.as_ref()).await
                    }
                    Some("drafts") => {
                        cli::execute_sdk_drafts(invocation, &mut sdk, cancel.clone()).await
                    }
                    Some("history") => {
                        cli::execute_sdk_global_history(invocation, &mut sdk, cancel.clone()).await
                    }
                    Some("workflows") => {
                        cli::execute_sdk_workflows(invocation, &mut sdk, cancel.clone()).await
                    }
                    Some("plans") => {
                        cli::execute_sdk_plans_with_delivery(
                            invocation,
                            &mut sdk,
                            cancel.clone(),
                            &store,
                            &api,
                        )
                        .await
                    }
                    Some("projects") => {
                        cli::execute_sdk_projects_with_delivery(
                            invocation,
                            &mut sdk,
                            cancel.clone(),
                            &store,
                            &api,
                        )
                        .await
                    }
                    _ => {
                        cli::execute_sdk_tasks_with_delivery(
                            invocation,
                            &mut sdk,
                            cancel.clone(),
                            &store,
                            &api,
                        )
                        .await
                    }
                }
            },
            &cancel,
            Duration::from_secs(2),
        )
        .await;
        return if is_draft_private_read(invocation) {
            match result {
                Ok(output) => finish_key_draft_output(output, &cancel, draft_private_gate.as_ref()),
                Err(error) => Err(error),
            }
        } else {
            result
        };
    }
    stages.record(Stage::StoreOpenStarted);
    cli::private_path::preflight(&resolved.state_dir)?;
    let store = RuntimeStore::new(Some(resolved.state_dir.clone()), globals.encrypted_vault)
        .await
        .map_err(|error| cli::private_path::explain(&resolved.state_dir, error))?;
    stages.record(Stage::StoreOpened);
    let mut passphrase = None;
    let login = invocation.command_path() == "login";
    if login && store.storage_mode().await?.is_some() {
        return Err(CliError::Invalid("Log out of this native profile before pairing another session; existing credentials were preserved.".into()));
    }
    let provisioning = cli::is_e2e_provisioning(&invocation);
    let signup = invocation.command_path() == "signup" || provisioning;
    if signup && store.storage_mode().await?.is_some() {
        return Err(CliError::Invalid("Log out of this native profile before creating another account; existing credentials were preserved.".into()));
    }
    let loaded = if login || signup {
        None
    } else {
        match store.load(None).await {
            Ok(session) => session,
            Err(Error::Locked)
                if io::stdin().is_terminal()
                    && store.storage_mode().await? == Some(StorageMode::EncryptedVault) =>
            {
                passphrase = Some(prompt("Credential vault passphrase: ", cancel.clone()).await?);
                store.load(passphrase.clone()).await?
            }
            Err(Error::Expired) => {
                store.clear().await?;
                return Err(Error::Expired.into());
            }
            Err(error) => return Err(error.into()),
        }
    };
    stages.record(Stage::CredentialsLoaded);
    let installed = server::installed_api(&resolved.state_dir)?;
    let api = resolved.api_url(loaded.as_ref(), installed.as_deref())?;
    let app = profile::application_origin(
        &api,
        std::env::var("OPENMATES_APP_URL")
            .ok()
            .filter(|s| !s.is_empty()),
        installed.as_deref(),
        server::installed_app(&resolved.state_dir)?,
    )?;
    let mut client = Client::with_options(
        &api,
        loaded,
        ClientOptions {
            identity: openmates_sdk::ClientIdentity::Cli,
            app_url: app,
            ..Default::default()
        },
    )?;
    client.set_private_operation_gate(Some(privacy::gate_for_profile(
        &resolved,
        directories.home_dir(),
    )));
    client.set_operation_cancel(cancel.clone());
    client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(
        openmates::native_cache_clock::cache_clock_evidence,
    )));
    // Only genuine credential absence admits the public anonymous transport.
    // Expired/locked/invalid sessions and explicit API keys have already returned
    // their own errors; a protected account can never silently become anonymous.
    if !login
        && client.session().is_none()
        && !policy.protected
        && trusted_path.is_none()
        && matches!(
            invocation.command_path().as_str(),
            "chats send" | "chats new" | "chats incognito"
        )
    {
        let anonymous = RuntimeStore::new(
            Some(profile::anonymous_state_dir(&resolved.state_dir, &api)?),
            false,
        )
        .await?;
        let anonymous_id = anonymous.anonymous_identity().await?;
        return cancellable(
            cli::execute_anonymous(&invocation, &mut client, &anonymous_id, cancel.clone()),
            &cancel,
            Duration::from_secs(2),
        )
        .await;
    }
    let mut saved_read_admission = None;
    let result = if signup {
        if globals.encrypted_vault {
            passphrase = Some(prompt("New credential vault passphrase: ", cancel.clone()).await?);
        }
        if provisioning {
            cli::execute_e2e_provisioning(&invocation, &mut client, &store, passphrase.clone(), &api, &cancel).await
        } else {
            cli::signup::execute(&invocation, &mut client, &store, passphrase.clone(), &cancel).await
        }
    } else if login {
        login_pair(
            &mut client,
            &store,
            &mut passphrase,
            globals.encrypted_vault,
            globals.json,
            &cancel,
            trusted_path.as_deref(),
        )
        .await
    } else if client.session().is_none() {
        Err(Error::Authentication.into())
    } else {
        // Restore authenticated local ciphertext before any save can replace it
        // with the new Client's initially empty snapshot. Never publish it here.
        let cache_load = session_runtime::command_cache_load(&invocation);
        session_runtime::restore_command_cache(&mut client, &store, passphrase.clone(), &cancel, cache_load)
            .await?;
        stages.record(Stage::CacheRestored);
        session_runtime::prepare_command_cache_admission(&mut client, &invocation);
        stages.record(Stage::AdmissionStarted);
        let admitted = session_runtime::FreshSessionAdmission::admit(
            &mut client,
            &store,
            passphrase.clone(),
            &cancel,
        )
        .await;
        stages.record(Stage::AdmissionFinished);
        match admitted {
            Err(error) => Err(error.into()),
            Ok(admission) => {
                if policy.protected || trusted_path.is_some() {
                    let expected = cli::trusted_account::load(&resolved.state_dir)?;
                    cli::trusted_account::verify(expected.as_deref(), admission.user()?)?;
                }
                // Consume the exclusive admitted lane before the final store
                // fence or ordinary command execution borrows Client again.
                let whoami_output = if invocation.command_path() == "whoami" {
                    Some(admission.whoami_output(&invocation))
                } else {
                    if matches!(
                        invocation.command_path().as_str(),
                        "chats show" | "chats messages" | "chats list" | "chats search"
                    ) {
                        admission.prepare_recovery()?;
                    } else {
                        drop(admission);
                    }
                    None
                };
                if matches!(
                    invocation.command_path().as_str(),
                    "whoami"
                        | "chats show"
                        | "chats messages"
                        | "chats list"
                        | "chats search"
                        | "drafts list"
                        | "drafts get"
                        | "embeds share"
                ) || cli::is_direct_apps_command(&invocation) {
                    // Capture the original profile scope BEFORE the command
                    // temporarily applies --personal/--team and restores it.
                    saved_read_admission = Some(if is_draft_private_read(&invocation) {
                        SavedReadOutputAdmission::capture_draft(&client, &store)
                    } else {
                        SavedReadOutputAdmission::capture(&client, &store)
                    });
                }
                let list_stage_observer = |event| stages.observe(event);
                stages.record(Stage::ReadDispatchStarted);
                let result = if let Some(output) = whoami_output {
                    output
                } else if cli::is_direct_apps_command(&invocation) {
                    cancellable(cli::execute_direct_apps_admitted(&invocation,&mut client,&store,cancel.clone()),
                        &cancel,Duration::from_secs(2)).await.and_then(|(output,scope)| {
                            if let Some(Ok(admission))=&mut saved_read_admission {admission.app_scope=Some(scope);}
                            output
                        })
                } else if invocation.command_path()=="embeds share" {
                    cancellable(cli::execute_cookie_embed_share_admitted(&invocation,&mut client,cancel.clone()),
                        &cancel,Duration::from_secs(2)).await.map(|(output,read)|{
                            if let Some(Ok(admission))=&mut saved_read_admission {admission.embed_share=Some(read);}
                            output
                        })
                } else {
                    cancellable(
                        cli::execute_with_foreground_recovery_admitted(
                            &invocation,
                            &mut client,
                            cancel.clone(),
                            cli::ApplicationRecoveryContext::new(&store, passphrase.clone())
                                .with_list_stage_observer(if stages.is_enabled() { Some(&list_stage_observer) } else { None }),
                        ),
                        &cancel,
                        Duration::from_secs(2),
                    )
                    .await.map(|(output,full_read)| {
                        if let Some(Ok(admission))=&mut saved_read_admission {
                            admission.full_read=full_read;
                        }
                        output
                    })
                };
                stages.record(Stage::ReadDispatchFinished);
                if matches!(&result, Err(CliError::Client(Error::Cancelled)))
                    && !invocation.boolean("incognito")
                    && invocation.command_path() != "chats incognito"
                    && matches!(
                        invocation.command_path().as_str(),
                        "chats send" | "chats new" | "chats answer-interactive"
                    )
                {
                    Err(CliError::RecoveryRequired {
                        chat_id: invocation.text("chat").map(str::to_owned),
                        source: Error::Cancelled,
                    })
                } else {
                    result
                }
            }
        }
    };
    stages.record(Stage::FinalPublicationStarted);
    match (result, saved_read_admission) {
        (Ok(output), Some(admission)) => {
            let pending = PendingOutput::new(output);
            #[cfg(test)]
            let pending = final_output_test_hook::capture(pending, &cancel);
            let admission=admission?;
            finish_saved_read_output(pending, persist_saved_read_final(&admission,&mut client,&store,passphrase,&cancel)).await
        }
        (Err(error),Some(Ok(admission))) if admission.app_scope.is_some() => {
            let mut pending=PendingAppError(Some(error));
            persist_saved_read_final(&admission,&mut client,&store,passphrase,&cancel).await?;
            Err(pending.0.take().ok_or(Error::Protocol)?)
        }
        (Err(error), Some(Ok(admission))) if store.generation() != admission.store_generation => {
            // Local revocation already fenced this Store. Do not start a new
            // save with the new generation and resurrect the stale Client;
            // equally, do not clear a newer owner's Store as error cleanup.
            client.forget_session();
            Err(error)
        }
        (Err(error), Some(Ok(admission))) if admission.draft_scope.is_some() => {
            if client.session().is_none() {
                // The original owner's authoritative revocation still clears its
                // durable credentials; the prior generation branch excludes newer stores.
                session_runtime::persist(&mut client, &store, passphrase).await?;
            } else if admission.check_credential_scope(&client, &store).is_ok() {
                // Even a cancelled read may have rotated credentials. Persist only
                // the original owner/key/generation, with no plaintext output.
                session_runtime::persist(&mut client, &store, passphrase).await?;
                admission.check_credential_scope(&client, &store)?;
            } else {
                client.forget_session();
            }
            Err(error)
        }
        (result, _) => {
            // Accepted mutation receipts/cancellation behavior is unchanged.
            session_runtime::persist(&mut client, &store, passphrase).await?;
            result
        }
    }
}

async fn persist_saved_read_final(
    admission:&SavedReadOutputAdmission,client:&mut Client,store:&RuntimeStore,
    passphrase:Option<Zeroizing<String>>,cancel:&CancellationToken,
)->Result<(),Error> {
    if cancel.is_cancelled() {return Err(Error::Cancelled);}
    admission.check(client,store)?;
    session_runtime::persist(client,store,passphrase).await?;
    #[cfg(test)]
    final_saved_read_persist_test_hook::wait(client,cancel).await;
    if cancel.is_cancelled() {return Err(Error::Cancelled);}
    admission.check(client,store)
}

fn is_draft_private_read(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "drafts list" | "drafts get"
    )
}
fn finish_key_draft_output(
    output: CliOutput,
    cancel: &CancellationToken,
    private_gate: &(dyn Fn() -> Result<(), Error> + Send + Sync),
) -> Result<CliOutput, CliError> {
    let pending = PendingOutput::new(output);
    #[cfg(test)]
    let pending = final_output_test_hook::capture(pending, cancel);
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    private_gate()?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    Ok(pending.release())
}
struct PendingAppError(Option<CliError>);
impl Drop for PendingAppError {
    fn drop(&mut self){if let Some(error)=self.0.as_mut(){cli::erase_error(error);}}
}
struct SavedReadOutputAdmission {
    api_url: String,
    owner: String,
    account_id: String,
    team_id: Option<String>,
    store_generation: u64,
    draft_scope: Option<openmates_sdk::client::DraftReadAdmission>,
    embed_share:Option<openmates_sdk::client::saved_embed::SavedEmbedRead>,
    app_scope: Option<openmates_sdk::client::DirectAppSkillAdmission>,
    full_read: Option<openmates_sdk::client::full_chat_read::FullChatReadAdmission>,
}
impl SavedReadOutputAdmission {
    fn capture(client: &Client, store: &RuntimeStore) -> Result<Self, Error> {
        let session = client.session().ok_or(Error::Authentication)?;
        let account_id = client.user()["id"]
            .as_str()
            .or_else(|| client.user()["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .ok_or(Error::Authentication)?
            .to_owned();
        Ok(Self {
            api_url: session.api_url.clone(),
            owner: session.hashed_email.clone(),
            account_id,
            team_id: session.active_team_id.clone(),
            store_generation: store.generation(),
            draft_scope: None,
            embed_share:None,
            app_scope: None,
            full_read: None,
        })
    }
    fn capture_draft(client: &Client, store: &RuntimeStore) -> Result<Self, Error> {
        let mut admission = Self::capture(client, store)?;
        admission.draft_scope = Some(client.draft_read_admission()?);
        Ok(admission)
    }
    fn check(&self, client: &Client, store: &RuntimeStore) -> Result<(), Error> {
        self.check_scope(client, store, true)
    }
    fn check_credential_scope(&self, client: &Client, store: &RuntimeStore) -> Result<(), Error> {
        self.check_scope(client, store, false)
    }
    fn check_scope(
        &self,
        client: &Client,
        store: &RuntimeStore,
        plaintext: bool,
    ) -> Result<(), Error> {
        if store.generation() != self.store_generation {
            return Err(Error::Cancelled);
        }
        if plaintext {
            if let Some(read)=&self.embed_share {read.check(client)?;}
            if let Some(app_scope)=&self.app_scope {app_scope.check(client)?;}
            if let Some(full_read)=&self.full_read {full_read.check(client)?;}
        }
        if let Some(scope) = &self.draft_scope {
            if plaintext {
                scope.check(client)?;
            } else {
                scope.check_credential_scope(client)?;
            }
        }
        let current = Self::capture(client, store)?;
        let session = client.session().ok_or(Error::Authentication)?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_millis();
        if session
            .paired_session_expires_at
            .is_some_and(|expires| u128::from(expires) <= now)
        {
            return Err(Error::Expired);
        }
        if current.api_url != self.api_url
            || current.owner != self.owner
            || current.account_id != self.account_id
            || current.team_id != self.team_id
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
/// App-private rendered output stays wiping through the LAST profile write.
struct PendingOutput {
    stdout: Zeroizing<String>,
    stderr: Zeroizing<String>,
    exit_code: u8,
    #[cfg(test)]
    wiped_on_drop: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
}
impl PendingOutput {
    fn new(output: CliOutput) -> Self {
        Self {
            stdout: Zeroizing::new(output.stdout),
            stderr: Zeroizing::new(output.stderr),
            exit_code: output.exit_code,
            #[cfg(test)]
            wiped_on_drop: None,
        }
    }
    fn release(mut self) -> CliOutput {
        CliOutput {
            stdout: std::mem::take(&mut *self.stdout),
            stderr: std::mem::take(&mut *self.stderr),
            exit_code: self.exit_code,
        }
    }
}
impl Drop for PendingOutput {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.stdout.zeroize();
        self.stderr.zeroize();
        #[cfg(test)]
        if let Some(observer) = &self.wiped_on_drop {
            observer.store(
                self.stdout.is_empty() && self.stderr.is_empty(),
                std::sync::atomic::Ordering::Release,
            );
        }
    }
}
#[cfg(test)]
mod final_output_test_hook {
    use super::{CancellationToken, PendingOutput};
    use std::{cell::RefCell, marker::PhantomData, rc::Rc};

    type Action = Box<dyn FnOnce(&mut PendingOutput, &CancellationToken)>;
    std::thread_local! {
        static ACTION: RefCell<Option<Action>> = const { RefCell::new(None) };
    }
    // A guard cannot migrate to another executor thread with an armed callback.
    pub(super) struct Guard(PhantomData<Rc<()>>);
    impl Drop for Guard {
        fn drop(&mut self) {
            ACTION.with(|slot| {
                slot.borrow_mut().take();
            });
        }
    }
    pub(super) fn install(
        action: impl FnOnce(&mut PendingOutput, &CancellationToken) + 'static,
    ) -> Guard {
        ACTION.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert!(slot.is_none(), "final-output test action already installed");
            *slot = Some(Box::new(action));
        });
        Guard(PhantomData)
    }
    pub(super) fn capture(mut pending: PendingOutput, cancel: &CancellationToken) -> PendingOutput {
        // Take first: callback execution never holds a RefCell borrow and each
        // test action can run only at one final-output boundary.
        let action = ACTION.with(|slot| slot.borrow_mut().take());
        if let Some(action) = action {
            action(&mut pending, cancel);
        }
        pending
    }
}

#[cfg(test)]
mod final_saved_read_persist_test_hook {
    use super::{CancellationToken,Client};
    use std::sync::{Arc,Mutex};
    #[derive(Default)]
    pub(super) struct Barrier {pub(super) persisted:tokio::sync::Notify,pub(super) resume:tokio::sync::Notify,action:Mutex<Option<Box<dyn FnOnce(&mut Client)+Send>>>}
    static ACTIVE:Mutex<Option<(CancellationToken,Arc<Barrier>)>>=Mutex::new(None);
    pub(super) struct Guard;
    impl Drop for Guard {fn drop(&mut self){ACTIVE.lock().unwrap().take();}}
    pub(super) fn install(cancel:&CancellationToken)->(Guard,Arc<Barrier>){
        let barrier=Arc::new(Barrier::default());let mut slot=ACTIVE.lock().unwrap();
        assert!(slot.is_none());*slot=Some((cancel.clone(),barrier.clone()));(Guard,barrier)
    }
    pub(super) fn install_action(cancel:&CancellationToken,action:impl FnOnce(&mut Client)+Send+'static)->(Guard,Arc<Barrier>){
        let (guard,barrier)=install(cancel);*barrier.action.lock().unwrap()=Some(Box::new(action));(guard,barrier)
    }
    pub(super) async fn wait(client:&mut Client,cancel:&CancellationToken){
        let barrier=ACTIVE.lock().unwrap().as_ref().filter(|(owner,_)|owner==cancel).map(|(_,barrier)|barrier.clone());
        if let Some(barrier)=barrier {
            barrier.persisted.notify_one();barrier.resume.notified().await;
            let action=barrier.action.lock().unwrap().take();
            if let Some(action)=action {action(client);}
        }
    }
}
async fn finish_saved_read_output(
    pending: PendingOutput,
    persist_and_revalidate: impl std::future::Future<Output = Result<(), Error>>,
) -> Result<CliOutput, CliError> {
    persist_and_revalidate.await?;
    Ok(pending.release())
}

/// Public reads and informational links resolve application configuration only.
/// In particular, this never constructs a RuntimeStore or loads its credentials.
fn public_client(
    globals: &GlobalArgs,
    environment: ProfileEnvironment,
    home: &std::path::Path,
    explicit_app: Option<String>,
) -> Result<Client, CliError> {
    let profile = profile::resolve(
        ProfileOptions {
            profile: globals.profile.clone(),
            state_dir: globals.state_dir.clone(),
            api_url: globals.api_url.clone(),
        },
        environment,
        home,
    )?;
    let installed_api = server::installed_api(&profile.state_dir)?;
    let installed_app = server::installed_app(&profile.state_dir)?;
    let api = profile.api_url(None, installed_api.as_deref())?;
    let mut client = Client::new(&api, None)?;
    client.set_identity(openmates_sdk::ClientIdentity::Cli);
    client.set_app_origin(profile::application_origin(
        &api,
        explicit_app,
        installed_api.as_deref(),
        installed_app,
    )?)?;
    Ok(client)
}

struct ServerContext {
    profile: profile::ResolvedProfile,
    account: ProfileOptions,
    home: PathBuf,
    encrypted_vault: bool,
    json_output: bool,
    api_key_selected: bool,
    trusted_guard: bool,
}

fn server_action(invocation: &Invocation) -> String {
    invocation
        .path
        .iter()
        .skip(1)
        .cloned()
        .collect::<Vec<_>>()
        .join(" ")
}

fn server_quick_flags(invocation: &Invocation) -> BTreeMap<String, serde_json::Value> {
    let mut flags = invocation
        .flags
        .iter()
        .filter(|(key, _)| {
            matches!(
                key.as_str(),
                "path" | "role" | "confirm-spend-credits" | "skip-quick-test"
            )
        })
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect::<BTreeMap<_, _>>();
    flags.insert("quick".into(), json!(true));
    flags
}

fn continuous_interval(flags: &BTreeMap<String, serde_json::Value>) -> Result<Duration, CliError> {
    let minutes = flags
        .get("interval")
        .map(|value| {
            value
                .as_str()
                .and_then(|value| value.parse::<u64>().ok())
                .filter(|minutes| (5..=10080).contains(minutes))
                .ok_or_else(|| {
                    CliError::Invalid("Update interval must be between 5 and 10080 minutes.".into())
                })
        })
        .transpose()?
        .unwrap_or(30);
    Ok(Duration::from_secs(minutes * 60))
}

async fn run_server(
    invocation: &Invocation,
    context: ServerContext,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    let action = server_action(invocation);
    if let Some(output) = server_group_usage(&action) {
        return output;
    }
    if action != "update" || !invocation.boolean("continuous") {
        let value = server_once(invocation, &context, cancel).await?;
        if !context.json_output
            && let Some(text) = server::human_text(&action, &value)
        {
            return Ok(CliOutput::text(text));
        }
        return server_output(&value, context.json_output);
    }
    let interval = continuous_interval(&invocation.flags)?;
    let window = invocation
        .text("window")
        .map(str::to_owned)
        .or_else(|| std::env::var("OPENMATES_UPDATE_WINDOW").ok());
    if let Some(window) = &window {
        server::update_window_allows(window, 0)?;
    }
    let mut cycle = Invocation {
        path: invocation.path.clone(),
        positionals: invocation.positionals.clone(),
        flags: invocation.flags.clone(),
    };
    cycle.flags.insert("continuous".into(), json!(false));
    cycle.flags.insert("continuous-update".into(), json!(true));
    eprintln!(
        "Running continuous updater every {} minutes. Interruptions finish the active host transaction before stopping.",
        interval.as_secs() / 60
    );
    loop {
        if cancel.is_cancelled() {
            break;
        }
        let now = time::OffsetDateTime::now_utc();
        let allowed = window
            .as_deref()
            .map(|window| {
                server::update_window_allows(
                    window,
                    u16::from(now.hour()) * 60 + u16::from(now.minute()),
                )
            })
            .transpose()?
            .unwrap_or(true);
        let value = if allowed {
            match server_once(&cycle, &context, cancel).await {
                Ok(value) => value,
                Err(error) => {
                    json!({"command":"update","status":"degraded","error":error.structured_error()})
                }
            }
        } else {
            json!({"command":"update","status":"not_run","reason":"outside_update_window"})
        };
        let output = server_output(&value, context.json_output)?;
        io::stdout()
            .write_all(output.stdout.as_bytes())
            .and_then(|()| io::stdout().flush())
            .map_err(|_| Error::Io)?;
        tokio::select! { biased; _ = cancel.cancelled() => break, _ = tokio::time::sleep(interval) => {} }
    }
    Ok(CliOutput {
        stdout: String::new(),
        stderr: String::new(),
        exit_code: 130,
    })
}

async fn server_once(
    invocation: &Invocation,
    context: &ServerContext,
    cancel: &CancellationToken,
) -> Result<serde_json::Value, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let action = server_action(invocation);
    let standalone = action == "test";
    let requested = standalone
        || action == "update"
            && invocation.boolean("quick-test")
            && !invocation.boolean("dry-run")
            && !invocation.boolean("skip-quick-test");
    if requested
        && (!invocation.boolean("confirm-spend-credits") || invocation.boolean("skip-quick-test"))
    {
        return Err(CliError::Invalid("Authenticated quick tests require --confirm-spend-credits and cannot use --skip-quick-test.".into()));
    }
    if standalone && !(invocation.boolean("quick") || invocation.boolean("quick-test")) {
        return Err(CliError::Invalid(
            "Use server test --quick --confirm-spend-credits.".into(),
        ));
    }
    if requested && context.api_key_selected {
        return Err(CliError::Unsupported { command: invocation.command_path(), reason: "Server quick tests require an explicit native session; API-key quick tests are not implemented.".into() });
    }
    // Host transactions retain their installation lock until completion. Do not
    // drop a blocking Docker/configuration transaction on a terminal signal.
    let mut value = if standalone {
        json!({"command":"test"})
    } else {
        server::execute_cancellable(
            &action,
            &invocation.positionals,
            &invocation.flags,
            &context.profile.state_dir,
            cancel,
        )
        .await?
    };
    if action == "status" {
        let installed = server::installed_api(&context.profile.state_dir)?;
        value["resolvedApiUrl"] = json!(context.profile.api_url(None, installed.as_deref())?);
    }
    if requested && value["dryRun"] != true {
        let quick =
            authenticated_server_quick(&server_quick_flags(invocation), context, cancel).await;
        match quick {
            Ok(result) => {
                value["quickTest"] = result["quickTest"].clone();
                if standalone {
                    value["role"] = result["role"].clone();
                }
            }
            Err(error) if !standalone => {
                // An authentication, storage or test failure must not erase the
                // completed update result from a scripting consumer's receipt.
                value["quickTest"] = json!({"status":"failed","cancelled":cancel.is_cancelled(),"error":error.structured_error(),"checks":[]});
            }
            Err(error) => return Err(error),
        }
    }
    if cancel.is_cancelled() && value["quickTest"].is_null() {
        value["cancelled"] = json!(true);
    }
    Ok(value)
}

async fn authenticated_server_quick(
    flags: &BTreeMap<String, serde_json::Value>,
    context: &ServerContext,
    cancel: &CancellationToken,
) -> Result<serde_json::Value, CliError> {
    if let Some(value) = server::quick_test_preflight(flags, &context.profile.state_dir).await? {
        return Ok(value);
    }
    let account = server_account_profile(context)?;
    let store = RuntimeStore::new(Some(account.state_dir.clone()), context.encrypted_vault).await?;
    let mut passphrase = None;
    let loaded = match store.load(None).await {
        Ok(session) => session,
        Err(Error::Locked)
            if io::stdin().is_terminal()
                && store.storage_mode().await? == Some(StorageMode::EncryptedVault) =>
        {
            passphrase = Some(prompt("Credential vault passphrase: ", cancel.clone()).await?);
            store.load(passphrase.clone()).await?
        }
        Err(error) => return Err(error.into()),
    }
    .ok_or(Error::Authentication)?;
    let installed = server::installed_api(&context.profile.state_dir)?;
    let api = account.api_url(Some(&loaded), installed.as_deref())?;
    let app = profile::application_origin(
        &api,
        std::env::var("OPENMATES_APP_URL")
            .ok()
            .filter(|value| !value.is_empty()),
        installed.as_deref(),
        server::installed_app(&context.profile.state_dir)?,
    )?;
    let mut client = Client::with_options(
        &api,
        Some(loaded),
        ClientOptions {
            identity: openmates_sdk::ClientIdentity::Cli,
            app_url: app,
            ..Default::default()
        },
    )?;
    client.set_private_operation_gate(Some(privacy::gate_for_profile(&account, &context.home)));
    client.set_operation_cancel(cancel.clone());
    session_runtime::restore_protected_cache(&mut client, &store, passphrase.clone(), cancel)
        .await?;
    // Paid quick tests can dispatch inference after admission. The existing
    // initial save below must remove any previous warm receipt first.
    client.invalidate_chat_list_freshness();
    let admitted = cancellable(
        async { client.validate_session().await.map_err(CliError::from) },
        cancel,
        Duration::from_secs(2),
    )
    .await;
    session_runtime::persist(&mut client, &store, passphrase.clone()).await?;
    admitted?;
    if cli::trusted_account::enforced_profile(&account.state_dir, context.trusted_guard)?.is_some()
    {
        let expected = cli::trusted_account::load(&account.state_dir)?;
        cli::trusted_account::verify(expected.as_deref(), client.user())?;
    }
    let result = cancellable(
        async {
            server::quick_test(&mut client, flags, &context.profile.state_dir, cancel)
                .await
                .map_err(CliError::from)
        },
        cancel,
        Duration::from_secs(8),
    )
    .await;
    // Persist header-first rotations even when later authentication/test bodies
    // fail, and only acknowledge credentials after durable local publication.
    session_runtime::persist(&mut client, &store, passphrase).await?;
    result
}

fn server_account_profile(context: &ServerContext) -> Result<profile::ResolvedProfile, CliError> {
    profile::resolve(
        ProfileOptions {
            profile: context.account.profile.clone(),
            state_dir: context.account.state_dir.clone(),
            api_url: context.account.api_url.clone(),
        },
        ProfileEnvironment::default(),
        &context.home,
    )
    .map_err(CliError::from)
}

/// npm behavior for the bare `server` group (help, exit 0) and for the `ai` and
/// `notifications` groups without a subcommand (usage error, exit 1).
fn server_group_usage(action: &str) -> Option<Result<CliOutput, CliError>> {
    let usage = match action {
        "" => {
            let mut help = cli::command();
            let server = help.find_subcommand_mut("server")?;
            return Some(Ok(CliOutput::text(server.render_long_help().to_string())));
        }
        "ai" => "Usage: openmates server ai models <add|list|test|remove>",
        "notifications" => {
            "Usage: openmates server notifications test --channel email|discord|webhook|all [--json]"
        }
        _ => return None,
    };
    Some(Err(CliError::Contract {
        code: "command_failed",
        message: usage.into(),
    }))
}

fn server_output(value: &serde_json::Value, json_output: bool) -> Result<CliOutput, CliError> {
    let mut output = if json_output {
        CliOutput::json(value)?
    } else {
        CliOutput::text(serde_json::to_string_pretty(value).map_err(|_| Error::Protocol)?)
    };
    output.exit_code = if value["cancelled"] == true || value["quickTest"]["cancelled"] == true {
        130
    } else if matches!(value["status"].as_str(), Some("failed" | "degraded"))
        || value["quickTest"]["status"] == "failed"
    {
        1
    } else {
        0
    };
    Ok(output)
}

async fn logout_native(store: &RuntimeStore, json_output: bool) -> Result<CliOutput, CliError> {
    let loaded = store.load(None).await.ok().flatten();
    let mut remote = loaded
        .and_then(|session| Client::new(&session.api_url.clone(), Some(session)).ok())
        .map(|mut client| {
            client.set_identity(openmates_sdk::ClientIdentity::Cli);
            client
        });
    let revoked = if let Some(client) = &mut remote {
        session_runtime::logout(client, store).await?;
        true
    } else {
        store.clear().await?;
        false
    };
    if json_output {
        CliOutput::json(
            &json!({"success":true,"local_credentials_cleared":true,"remote_revoked":revoked}),
        )
    } else {
        Ok(CliOutput::text(if revoked {
            "Logged out."
        } else {
            "Local credentials cleared. Remote revocation could not be confirmed without unlocked credentials."
        }))
    }
}

async fn login_pair(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: &mut Option<Zeroizing<String>>,
    vault: bool,
    json_output: bool,
    cancel: &CancellationToken,
    trusted_path: Option<&std::path::Path>,
) -> Result<CliOutput, CliError> {
    if !io::stdin().is_terminal() {
        return Err(CliError::Invalid(
            "Pairing requires an interactive terminal. Run openmates login in a terminal.".into(),
        ));
    }
    let challenge = client.begin_pair().await?;
    eprintln!(
        "Open this link in your signed-in browser to approve pairing:\n{}",
        challenge.login_url
    );
    let expires = std::time::Instant::now()
        + Duration::from_secs(challenge.expires_at.saturating_sub(now_seconds()));
    let result=async {
        loop {
            if cancel.is_cancelled(){return Err(Error::Cancelled);}
            if std::time::Instant::now()>=expires{return Err(Error::Expired);}
            if client.poll_pair().await?=="approved"{break;}
            tokio::select!{_=cancel.cancelled()=>return Err(Error::Cancelled),_=tokio::time::sleep(Duration::from_secs(1))=>{}}
        }
        let pin=prompt("Pairing PIN from the browser: ",cancel.clone()).await?;
        client.submit_pair_pin(&pin).await?;
        loop {
            if cancel.is_cancelled(){return Err(Error::Cancelled);}
            if std::time::Instant::now()>=expires{return Err(Error::Expired);}
            if client.finish_pair().await?{break;}
            tokio::select!{_=cancel.cancelled()=>return Err(Error::Cancelled),_=tokio::time::sleep(Duration::from_secs(1))=>{}}
        }
        if let Some(path)=trusted_path {
            client.validate_session().await?;
            cli::trusted_account::save(path,client.user()["id"].as_str().unwrap_or("")).map_err(|_|Error::Forbidden)?;
        }
        if vault{*passphrase=Some(prompt("New credential vault passphrase: ",cancel.clone()).await?);}
        store.begin_session_cancellable(client.clone_session().ok_or(Error::Authentication)?,cancel.clone()).await?;
        session_runtime::persist(client,store,passphrase.clone()).await?;
        if cancel.is_cancelled(){return Err(Error::Cancelled);}
        client.acknowledge_pair().await?;
        if cancel.is_cancelled(){return Err(Error::Cancelled);}
        Ok::<_,Error>(())
    }.await;
    if let Err(error) = result {
        let cleanup = store.clear().await;
        let _ = client.cancel_pair().await;
        let _ = client.logout().await;
        cleanup?;
        return Err(error.into());
    }
    let mode = store.storage_mode().await?;
    if json_output {
        CliOutput::json(&json!({"success":true,"storage_mode":mode}))
    } else {
        Ok(CliOutput::text(format!(
            "Logged in. Credential storage: {}.",
            serde_json::to_string(&mode).map_err(|_| Error::Protocol)?
        )))
    }
}

fn now_seconds() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
async fn prompt(
    label: &'static str,
    cancel: CancellationToken,
) -> Result<Zeroizing<String>, Error> {
    tokio::task::spawn_blocking(move || {
        if !io::stdin().is_terminal() {
            return Err(Error::Invalid(
                "Secret input requires an interactive terminal.",
            ));
        }
        struct RawGuard {
            was_raw: bool,
        }
        impl Drop for RawGuard {
            fn drop(&mut self) {
                if !self.was_raw {
                    let _ = crossterm::terminal::disable_raw_mode();
                }
            }
        }
        let was_raw = crossterm::terminal::is_raw_mode_enabled()?;
        crossterm::terminal::enable_raw_mode()?;
        let _guard = RawGuard { was_raw };
        // The label is the readiness boundary for interactive callers. Install
        // raw/no-echo mode and its restoration guard BEFORE soliciting input.
        eprint!("{label}");
        io::stderr().flush()?;
        let mut value = Zeroizing::new(String::new());
        loop {
            use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if !event::poll(Duration::from_millis(50))? {
                continue;
            }
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Release {
                    continue;
                }
                match key.code {
                    KeyCode::Enter => {
                        eprint!("\r\n");
                        break;
                    }
                    KeyCode::Esc => return Err(Error::Cancelled),
                    KeyCode::Char('c' | 'd') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                        return Err(Error::Cancelled);
                    }
                    KeyCode::Backspace => {
                        value.pop();
                    }
                    KeyCode::Char(c) if !c.is_control() && value.len() < 4096 => value.push(c),
                    _ => {}
                }
            }
        }
        Ok(value)
    })
    .await
    .map_err(|_| Error::Io)?
}

struct SignalGuard(tokio::task::JoinHandle<()>);
impl SignalGuard {
    fn new(cancel: CancellationToken) -> Result<Self, Error> {
        #[cfg(unix)]
        {
            use tokio::signal::unix::{SignalKind, signal};
            let mut interrupt = signal(SignalKind::interrupt())?;
            let mut terminate = signal(SignalKind::terminate())?;
            let mut hangup = signal(SignalKind::hangup())?;
            Ok(Self(tokio::spawn(async move {
                tokio::select! {_=interrupt.recv()=>{},_=terminate.recv()=>{},_=hangup.recv()=>{}}
                cancel.cancel();
            })))
        }
        #[cfg(not(unix))]
        {
            Ok(Self(tokio::spawn(async move {
                let _ = tokio::signal::ctrl_c().await;
                cancel.cancel();
            })))
        }
    }
}
impl Drop for SignalGuard {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn cancellable<T>(
    operation: impl std::future::Future<Output = Result<T, CliError>>,
    cancel: &CancellationToken,
    grace: Duration,
) -> Result<T, CliError> {
    tokio::pin!(operation);
    tokio::select! {biased;result=&mut operation=>result,_=cancel.cancelled()=>tokio::time::timeout(grace,&mut operation).await.unwrap_or(Err(Error::Cancelled.into()))}
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn public_client_does_not_open_locked_cookie_profile_or_inherit_api_key() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let state = directory.path().join("profile");
        let _locked = RuntimeStore::new(Some(state.clone()), true).await.unwrap();
        let credential_file = state.join("session.json");
        std::fs::write(&credential_file, b"must not parse or unlock").unwrap();
        let globals = GlobalArgs {
            demo: false,
            api_url: Some("https://api.example.test".into()),
            state_dir: Some(state.clone()),
            encrypted_vault: true,
            profile: None,
            json: true,
            api_key: Some(Zeroizing::new("must-not-be-inherited".into())),
        };
        let client = public_client(
            &globals,
            ProfileEnvironment::default(),
            directory.path(),
            Some("https://app.example.test".into()),
        )
        .unwrap_or_else(|_| panic!("public configuration must not unlock a profile"));
        assert!(client.session().is_none());
        assert_eq!(client.application_url(), "https://app.example.test");
        assert_eq!(
            std::fs::read(credential_file).unwrap(),
            b"must not parse or unlock"
        );
        assert!(!state.join("device.json").exists());
        assert!(!state.join("revocation.json").exists());
    }
    #[tokio::test]
    async fn unconfirmed_paid_test_and_cancelled_server_command_touch_no_profile_or_installation() {
        let temp = tempfile::tempdir().unwrap();
        let state = temp.path().join("unopened");
        let context = ServerContext {
            account: ProfileOptions::default(),
            profile: profile::ResolvedProfile {
                state_dir: state.clone(),
                profile: None,
                api_url_override: None,
            },
            home: temp.path().to_path_buf(),
            encrypted_vault: true,
            json_output: true,
            api_key_selected: false,
            trusted_guard: false,
        };
        for action in ["test", "update"] {
            let call = Invocation {
                path: vec!["server".into(), action.into()],
                positionals: vec![],
                flags: BTreeMap::from([
                    ("quick".into(), json!(true)),
                    ("quick-test".into(), json!(true)),
                ]),
            };
            assert!(matches!(
                server_once(&call, &context, &CancellationToken::new()).await,
                Err(CliError::Invalid(_))
            ));
            assert!(!state.exists());
        }
        let cancel = CancellationToken::new();
        cancel.cancel();
        let call = Invocation {
            path: vec!["server".into(), "update".into()],
            positionals: vec![],
            flags: BTreeMap::new(),
        };
        assert!(matches!(
            server_once(&call, &context, &cancel).await,
            Err(CliError::Client(Error::Cancelled))
        ));
        assert!(!state.exists());
    }

    #[test]
    fn paid_server_test_uses_named_account_without_changing_host_state_or_account_pin() {
        let temp = tempfile::tempdir().unwrap();
        let host_state = temp.path().join(".openmates-rust");
        let context = ServerContext {
            profile: profile::ResolvedProfile {
                state_dir: host_state.clone(),
                profile: None,
                api_url_override: None,
            },
            account: ProfileOptions {
                profile: Some("codex-personal".into()),
                state_dir: None,
                api_url: Some("https://api.dev.openmates.org".into()),
            },
            home: temp.path().to_path_buf(),
            encrypted_vault: false,
            json_output: true,
            api_key_selected: false,
            trusted_guard: true,
        };
        let account = server_account_profile(&context).unwrap_or_else(|error| panic!("{error}"));
        assert_eq!(
            account.state_dir,
            host_state.join("profiles/codex-personal")
        );
        assert_eq!(context.profile.state_dir, host_state);
        let store =
            openmates::storage::Store::encrypted_vault(account.state_dir.clone())
                .unwrap();
        cli::trusted_account::save(store.state_dir(), "expected-fixture-user")
            .unwrap_or_else(|error| panic!("{error}"));
        let expected = cli::trusted_account::load(&account.state_dir)
            .unwrap_or_else(|error| panic!("{error}"));
        assert!(
            cli::trusted_account::verify(expected.as_deref(), &json!({"id":"other-fixture-user"}))
                .is_err()
        );
        assert!(
            cli::trusted_account::load(&context.profile.state_dir)
                .unwrap_or_else(|error| panic!("{error}"))
                .is_none()
        );
        assert_eq!(
            account.api_url(None, None).unwrap(),
            "https://api.dev.openmates.org"
        );
        assert!(!account.state_dir.join("session.json").exists());
    }

    #[test]
    fn invalid_continuous_interval_cannot_overflow_or_become_a_busy_update_loop() {
        for input in [
            json!("0"),
            json!("4"),
            json!("10081"),
            json!("18446744073709551615"),
            json!("5junk"),
            json!(5),
        ] {
            assert!(continuous_interval(&BTreeMap::from([("interval".into(), input)])).is_err());
        }
        assert_eq!(
            continuous_interval(&BTreeMap::new()).unwrap_or_else(|error| panic!("{error}")),
            Duration::from_secs(1800)
        );
        assert_eq!(
            continuous_interval(&BTreeMap::from([("interval".into(), json!("5"))]))
                .unwrap_or_else(|error| panic!("{error}")),
            Duration::from_secs(300)
        );
    }
    #[test]
    fn partial_delivery_and_failed_quick_tests_keep_json_and_nonzero_status() {
        for (value, status) in [
            (
                json!({"status":"degraded","deliveryState":"partial_failure"}),
                1,
            ),
            (
                json!({"status":"success","quickTest":{"status":"failed"}}),
                1,
            ),
            (
                json!({"status":"success","quickTest":{"status":"failed","cancelled":true}}),
                130,
            ),
            (
                json!({"status":"success","quickTest":{"status":"not_run"}}),
                0,
            ),
        ] {
            let output = server_output(&value, true).unwrap_or_else(|error| panic!("{error}"));
            assert_eq!(output.exit_code, status);
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&output.stdout).unwrap(),
                value
            );
        }
    }
    #[tokio::test]
    async fn locked_vault_logout_clears_credentials_and_cache_without_unlock_or_network() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let session = openmates::storage::Session {
            api_url: "https://never-contact.example.invalid".into(),
            session_id: "synthetic".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        store
            .save(
                session.clone(),
                Some(Zeroizing::new("synthetic vault password".into())),
            )
            .await
            .unwrap();
        store
            .write_cache(
                session.hashed_email.clone(),
                "synthetic-cache".into(),
                session.master_key.clone(),
                json!({"private":"synthetic"}),
            )
            .await
            .unwrap();
        assert!(matches!(store.load(None).await, Err(Error::Locked)));
        let output = tokio::time::timeout(Duration::from_secs(2), logout_native(&store, true))
            .await
            .unwrap()
            .unwrap_or_else(|error| panic!("{error}"));
        let result: serde_json::Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(result["local_credentials_cleared"], true);
        assert_eq!(result["remote_revoked"], false);
        assert!(store.load(None).await.unwrap().is_none());
        assert!(!std::fs::read_dir(directory.path()).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("cache-")
        }));
    }
    #[tokio::test]
    async fn stalled_operation_is_cancelled_after_bounded_grace() {
        let cancel = CancellationToken::new();
        cancel.cancel();
        let result = cancellable(
            std::future::pending::<Result<(), CliError>>(),
            &cancel,
            Duration::from_millis(20),
        )
        .await;
        assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
    }
    #[tokio::test]
    async fn completed_operation_wins_cancellation_without_losing_admission() {
        let cancel = CancellationToken::new();
        cancel.cancel();
        assert_eq!(
            cancellable(
                async { Ok::<_, CliError>(42) },
                &cancel,
                Duration::from_millis(20)
            )
            .await
            .ok(),
            Some(42)
        );
    }
    #[tokio::test]
    async fn dropped_final_saved_read_persist_wipes_output_without_handoff() {
        tokio::time::timeout(Duration::from_secs(2), async {
            let wiped = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
            let mut pending = PendingOutput::new(CliOutput {
                stdout: "synthetic private saved chat".into(),
                stderr: "synthetic private diagnostics".into(),
                exit_code: 0,
            });
            pending.wiped_on_drop = Some(wiped.clone());
            let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
            let caller = tokio::spawn(finish_saved_read_output(pending, async move {
                entered_tx.send(()).ok();
                std::future::pending::<Result<(), Error>>().await
            }));
            entered_rx.await.ok().unwrap();
            assert!(!wiped.load(std::sync::atomic::Ordering::Acquire));
            caller.abort();
            assert!(caller.await.err().unwrap().is_cancelled());
            assert!(wiped.load(std::sync::atomic::Ordering::Acquire));
        })
        .await
        .ok()
        .unwrap();
    }
    #[tokio::test]
    async fn final_saved_read_guard_failure_suppresses_and_wipes_completed_output() {
        let wiped = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let mut pending = PendingOutput::new(CliOutput {
            stdout: "synthetic private saved chat".into(),
            stderr: String::new(),
            exit_code: 0,
        });
        pending.wiped_on_drop = Some(wiped.clone());
        let result = finish_saved_read_output(pending, async { Err(Error::Cancelled) }).await;
        assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
        assert!(wiped.load(std::sync::atomic::Ordering::Acquire));
    }

    struct FinalFenceNoKeyring;
    impl openmates::storage::CredentialBackend for FinalFenceNoKeyring {
        fn get(
            &self,
            _: &str,
        ) -> Result<Zeroizing<Vec<u8>>, openmates::storage::KeyringFailure> {
            Err(openmates::storage::KeyringFailure::Unavailable)
        }
        fn set(
            &self,
            _: &str,
            _: &[u8],
        ) -> Result<(), openmates::storage::KeyringFailure> {
            Err(openmates::storage::KeyringFailure::Unavailable)
        }
        fn delete(&self, _: &str) -> Result<(), openmates::storage::KeyringFailure> {
            Err(openmates::storage::KeyringFailure::Unavailable)
        }
    }
    fn final_fence_snapshot() -> serde_json::Value {
        json!({"chats":{"11111111-1111-4111-8111-111111111111":{
            "id":"11111111-1111-4111-8111-111111111111","encrypted_title":"synthetic-warm-ciphertext"}},
            "wrappers":[],"history":{},"embeds":{},"embed_keys":[],"team_wrapped_key":null})
    }
    async fn final_fence_fixture() -> (tempfile::TempDir, String, tokio::task::JoinHandle<usize>) {
        final_fence_fixture_for(None).await
    }
    async fn final_fence_fixture_for(
        draft: Option<serde_json::Value>,
    ) -> (tempfile::TempDir, String, tokio::task::JoinHandle<usize>) {
        final_fence_fixture_with_apps(draft,false).await
    }
    async fn final_fence_fixture_with_apps(
        draft:Option<serde_json::Value>,direct_apps:bool,
    )->(tempfile::TempDir,String,tokio::task::JoinHandle<usize>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        // Do not mutate shared process environment or admit an installed account.
        for name in [
            "OPENMATES_API_KEY",
            "OPENMATES_PROFILE",
            "OPENMATES_ACCOUNT_GUARD",
            "OPENMATES_REQUIRE_TRUSTED_ACCOUNT",
            "OPENMATES_APP_URL",
        ] {
            assert!(
                std::env::var_os(name).is_none(),
                "isolated CI must unset {name}"
            );
        }
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let store = openmates::storage::Store::with_backend(
            directory.path().to_path_buf(),
            std::sync::Arc::new(FinalFenceNoKeyring),
        )
        .unwrap();
        let session = openmates::storage::Session {
            api_url: api.clone(),
            session_id: "synthetic-final-fence-session".into(),
            cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-original".into())]),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-final-fence-owner".into(),
            user_email_salt: "synthetic-salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        store.save_session(&session, None).unwrap();
        store
            .write_cache(
                &session.hashed_email,
                &session_runtime::cache_key(&session),
                &session.master_key,
                &final_fence_snapshot(),
            )
            .unwrap();
        drop(store);
        let peer = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            let mut chunk = [0u8; 2048];
            let end = loop {
                let n = socket.read(&mut chunk).await.unwrap();
                assert_ne!(n, 0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                    break end + 4;
                }
            };
            let headers = std::str::from_utf8(&bytes[..end]).unwrap();
            assert!(headers.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));
            let length: usize = headers
                .lines()
                .filter_map(|v| v.split_once(':'))
                .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                .unwrap()
                .1
                .trim()
                .parse()
                .unwrap();
            while bytes.len() < end + length {
                let n = socket.read(&mut chunk).await.unwrap();
                assert_ne!(n, 0);
                bytes.extend_from_slice(&chunk[..n]);
            }
            let payload: serde_json::Value =
                serde_json::from_slice(&bytes[end..end + length]).unwrap();
            assert_eq!(payload["session_id"], "synthetic-final-fence-session");
            let body = r#"{"success":true,"ws_token":"synthetic-final-ws","user":{"id":"synthetic-final-fence-account"}}"#;
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=synthetic-final-rotated; Path=/; HttpOnly\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            if direct_apps {
                let mut observed=1usize;
                loop {
                    assert!(observed<8,"bounded direct CLI protocol");
                    let (mut socket,_)=listener.accept().await.unwrap();let mut bytes=vec![];let mut part=[0u8;4096];
                    let (end,length)=loop {
                        let n=socket.read(&mut part).await.unwrap();assert!(n>0);bytes.extend_from_slice(&part[..n]);
                        if let Some(end)=bytes.windows(4).position(|b|b==b"\r\n\r\n") {
                            let headers=std::str::from_utf8(&bytes[..end]).unwrap();
                            let len=headers.lines().filter_map(|s|s.split_once(':')).find(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap()).unwrap_or(0);
                            break(end+4,len);
                        }
                    };
                    while bytes.len()<end+length{let n=socket.read(&mut part).await.unwrap();assert!(n>0);bytes.extend_from_slice(&part[..n]);}
                    let headers=std::str::from_utf8(&bytes[..end]).unwrap();
                    assert!(headers.to_ascii_lowercase().contains("cookie:"));assert!(!headers.to_ascii_lowercase().contains("authorization:"));
                    let line=headers.lines().next().unwrap();let payload=if length>0{serde_json::from_slice::<serde_json::Value>(&bytes[end..end+length]).unwrap()}else{json!(null)};
                    observed+=1;
                    let final_result=line.starts_with("POST /v1/apps/code/skills/get_docs ");
                    let body=if final_result {
                        assert_eq!(payload,json!({"library":"React","question":"Synthetic docs?"}));
                        json!({"success":true,"credits_charged":0,"data":{"documentation":"Synthetic documentation"}})
                    }else if line.starts_with("GET /v1/apps/code/skills/get_docs/details ") {
                        json!({"app_id":"code","skill_id":"get_docs","name":"Docs","execution_available":true,"input_schema":{"type":"object","properties":{"library":{"type":"string"},"question":{"type":"string"}},"required":["library","question"]}})
                    }else {
                        assert!(line.starts_with("POST /v1/auth/session "),"no retained-result/chat route is admitted");
                        json!({"success":true,"ws_token":"synthetic-final-ws","user":{"id":"synthetic-final-fence-account"}})
                    }.to_string();
                    socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                    if final_result{return observed;}
                }
            }
            if let Some(draft) = draft {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                let mut chunk = [0; 2048];
                loop {
                    let n = socket.read(&mut chunk).await.unwrap();
                    assert!(n > 0);
                    request.extend_from_slice(&chunk[..n]);
                    if request.windows(4).any(|v| v == b"\r\n\r\n") {
                        break;
                    }
                }
                let headers = String::from_utf8(request).unwrap();
                assert!(
                    headers.starts_with("GET /v1/drafts/11111111-1111-4111-8111-111111111111 ")
                );
                assert!(
                    headers
                        .to_lowercase()
                        .contains("auth_refresh_token=synthetic-final-rotated")
                );
                assert!(!headers.to_lowercase().contains("authorization:"));
                let body = json!({"draft":draft}).to_string();
                socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                2
            } else {
                1
            }
        });
        (directory, api, peer)
    }
    struct InitialFinalFencePublication {
        cache: PathBuf,
        cache_bytes: Vec<u8>,
        session_bytes: Vec<u8>,
    }
    fn observe_final_fence_initial_publication(
        pending: &mut PendingOutput,
        path: &std::path::Path,
        wiped: std::sync::Arc<std::sync::atomic::AtomicBool>,
    ) -> InitialFinalFencePublication {
        assert!(pending.stdout.contains("synthetic-final-fence-account"));
        assert!(pending.stderr.is_empty());
        pending.wiped_on_drop = Some(wiped);
        // Runtime has awaited initial persistence and is paused synchronously
        // at PendingOutput capture. This read-only injected backend deliberately
        // avoids its lifetime runtime lock without touching any OS keyring.
        let store = openmates::storage::Store::with_backend(
            path.to_path_buf(),
            std::sync::Arc::new(FinalFenceNoKeyring),
        )
        .unwrap();
        let saved = store.load_session(None).unwrap().unwrap();
        assert_eq!(
            saved.cookies["auth_refresh_token"],
            "synthetic-final-rotated"
        );
        assert_eq!(saved.ws_token.as_deref(), Some("synthetic-final-ws"));
        assert_eq!(
            store
                .read_cache(
                    &saved.hashed_email,
                    &session_runtime::cache_key(&saved),
                    &saved.master_key
                )
                .unwrap(),
            Some(final_fence_snapshot())
        );
        let cache = std::fs::read_dir(path)
            .unwrap()
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .find(|file| {
                file.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cache-")
                    && file.extension().is_some_and(|ext| ext == "json")
            })
            .unwrap();
        InitialFinalFencePublication {
            cache_bytes: std::fs::read(&cache).unwrap(),
            cache,
            session_bytes: std::fs::read(path.join("session.json")).unwrap(),
        }
    }
    async fn run_final_fence_whoami(
        api: &str,
        path: &std::path::Path,
    ) -> Result<CliOutput, CliError> {
        let parsed = cli::parse_from([
            "openmates",
            "--api-url",
            api,
            "--state-dir",
            path.to_str().unwrap(),
            "whoami",
            "--json",
        ])
        .unwrap_or_else(|_| panic!("valid isolated final-fence command"));
        tokio::time::timeout(
            Duration::from_secs(10),
            run(parsed.globals, parsed.invocation.unwrap()),
        )
        .await
        .unwrap()
    }
    #[tokio::test(flavor = "current_thread")]
    async fn actual_runtime_whoami_late_cancel_after_pending_capture_withholds_and_wipes_output() {
        use std::sync::{
            Arc, Mutex,
            atomic::{AtomicBool, Ordering},
        };
        let (directory, api, peer) = final_fence_fixture().await;
        let proof = Arc::new(Mutex::new(None));
        let callback_proof = proof.clone();
        let wiped = Arc::new(AtomicBool::new(false));
        let callback_wiped = wiped.clone();
        let path = directory.path().to_path_buf();
        let _guard = final_output_test_hook::install(move |pending, original_cancel| {
            let observed = observe_final_fence_initial_publication(pending, &path, callback_wiped);
            assert!(callback_proof.lock().unwrap().replace(observed).is_none());
            original_cancel.cancel();
        });
        let result = run_final_fence_whoami(&api, directory.path()).await;
        assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
        assert!(wiped.load(Ordering::Acquire));
        let proof = proof
            .lock()
            .unwrap()
            .take()
            .expect("exact final-output barrier reached");
        assert_eq!(
            std::fs::read(&proof.cache).unwrap(),
            proof.cache_bytes,
            "cancelled final fence publishes no cache replacement"
        );
        assert_eq!(
            std::fs::read(directory.path().join("session.json")).unwrap(),
            proof.session_bytes,
            "late cancellation precedes the final credential save"
        );
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), false)
            .await
            .unwrap();
        assert_eq!(
            store.load(None).await.unwrap().unwrap().cookies["auth_refresh_token"],
            "synthetic-final-rotated"
        );
        assert_eq!(peer.await.unwrap(), 1);
    }
    #[cfg(unix)]
    #[tokio::test(flavor = "current_thread")]
    async fn actual_runtime_whoami_final_save_never_touches_an_obstructed_cache() {
        use std::sync::{
            Arc, Mutex,
            atomic::AtomicBool,
        };
        let (directory, api, peer) = final_fence_fixture().await;
        let proof = Arc::new(Mutex::new(None));
        let callback_proof = proof.clone();
        let wiped = Arc::new(AtomicBool::new(false));
        let callback_wiped = wiped.clone();
        let path = directory.path().to_path_buf();
        let _guard = final_output_test_hook::install(move |pending, _| {
            let observed = observe_final_fence_initial_publication(pending, &path, callback_wiped);
            let blocked = observed.cache.with_extension("blocked");
            std::fs::rename(&observed.cache, &blocked).unwrap();
            std::os::unix::fs::symlink(&blocked, &observed.cache).unwrap();
            assert!(callback_proof.lock().unwrap().replace(observed).is_none());
        });
        // whoami defers the sync cache: its final save publishes the rotated
        // credentials only and never reads, follows or replaces the cache.
        let result = run_final_fence_whoami(&api, directory.path()).await;
        assert!(result.is_ok());
        let proof = proof
            .lock()
            .unwrap()
            .take()
            .expect("exact final-output barrier reached");
        assert!(
            std::fs::symlink_metadata(&proof.cache)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        assert_eq!(
            std::fs::read(proof.cache.with_extension("blocked")).unwrap(),
            proof.cache_bytes,
            "the deferred cache is byte-identical"
        );
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), false)
            .await
            .unwrap();
        let saved = store.load(None).await.unwrap().unwrap();
        assert_eq!(
            saved.cookies["auth_refresh_token"],
            "synthetic-final-rotated"
        );
        assert_eq!(peer.await.unwrap(), 1);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn actual_cookie_draft_output_late_cancel_is_withheld_before_final_cache_persist() {
        use std::sync::{
            Arc, Mutex,
            atomic::{AtomicBool, Ordering},
        };
        let cipher =
            openmates_sdk::crypto::encrypt_combined("synthetic final private draft", &[7; 32])
                .unwrap();
        let draft = json!({"chat_id":"11111111-1111-4111-8111-111111111111","encrypted_draft_md":cipher,"encrypted_draft_preview":null,"draft_v":2});
        let (directory, api, peer) = final_fence_fixture_for(Some(draft)).await;
        let path = directory.path().to_path_buf();
        let before = Arc::new(Mutex::new(None));
        let captured = before.clone();
        let wiped = Arc::new(AtomicBool::new(false));
        let callback_wiped = wiped.clone();
        let _hook = final_output_test_hook::install(move |pending, cancel| {
            assert!(pending.stdout.contains("synthetic final private draft"));
            pending.wiped_on_drop = Some(callback_wiped);
            let store = openmates::storage::Store::with_backend(
                path.clone(),
                Arc::new(FinalFenceNoKeyring),
            )
            .unwrap();
            let saved = store.load_session(None).unwrap().unwrap();
            assert_eq!(
                saved.cookies["auth_refresh_token"],
                "synthetic-final-rotated"
            );
            assert_eq!(
                store
                    .read_cache(
                        &saved.hashed_email,
                        &session_runtime::cache_key(&saved),
                        &saved.master_key
                    )
                    .unwrap(),
                Some(final_fence_snapshot())
            );
            let cache = std::fs::read_dir(&path)
                .unwrap()
                .map(|v| v.unwrap().path())
                .find(|p| {
                    p.file_name()
                        .unwrap()
                        .to_string_lossy()
                        .starts_with("cache-")
                        && p.extension().is_some_and(|e| e == "json")
                })
                .unwrap();
            let bytes = std::fs::read(&cache).unwrap();
            *captured.lock().unwrap() = Some((cache, bytes));
            cancel.cancel();
        });
        let parsed = cli::parse_from([
            "openmates",
            "--api-url",
            &api,
            "--state-dir",
            directory.path().to_str().unwrap(),
            "drafts",
            "get",
            "11111111-1111-4111-8111-111111111111",
            "--refresh",
            "--json",
        ])
        .unwrap();
        let result = tokio::time::timeout(
            Duration::from_secs(10),
            run(parsed.globals, parsed.invocation.unwrap()),
        )
        .await
        .unwrap();
        assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
        assert!(wiped.load(Ordering::Acquire));
        let (cache, bytes) = before
            .lock()
            .unwrap()
            .take()
            .expect("actual draft PendingOutput captured");
        assert_eq!(std::fs::read(cache).unwrap(), bytes);
        assert_eq!(peer.await.unwrap(), 2);
    }
    #[test]
    fn explicit_key_draft_final_gate_has_no_cookie_store_and_wipes_denied_output() {
        use std::sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        };
        for privacy_denial in [false, true] {
            let cancel = CancellationToken::new();
            let wiped = Arc::new(AtomicBool::new(false));
            let observer = wiped.clone();
            let _hook = final_output_test_hook::install(move |pending, token| {
                assert!(pending.stdout.contains("synthetic private key draft"));
                pending.wiped_on_drop = Some(observer);
                if !privacy_denial {
                    token.cancel();
                }
            });
            let output = CliOutput {
                stdout: "synthetic private key draft".into(),
                stderr: String::new(),
                exit_code: 0,
            };
            let result = finish_key_draft_output(output, &cancel, &move || {
                if privacy_denial {
                    Err(Error::Forbidden)
                } else {
                    Ok(())
                }
            });
            assert!(matches!(
                result,
                Err(CliError::Client(Error::Cancelled | Error::Forbidden))
            ));
            assert!(wiped.load(Ordering::Acquire));
        }
    }
    #[tokio::test]
    async fn draft_saved_admission_rejects_store_generation_change_without_releasing_output() {
        let directory = tempfile::tempdir().unwrap();
        let store = RuntimeStore::new(Some(directory.path().join("profile")), false)
            .await
            .unwrap();
        let api = "https://api.example.invalid";
        let session = openmates_sdk::Session {
            api_url: api.into(),
            session_id: "synthetic".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let client = Client::new(api, Some(session)).unwrap();
        // The shared opaque scope is independently covered for principal/key and
        // Client generation; this boundary adds durable Store revocation.
        let scope = client.draft_read_admission().unwrap();
        assert!(scope.check(&client).is_ok());
        let generation = store.generation();
        store.revoke().await.unwrap();
        assert_ne!(generation, store.generation());
        let wiped = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let mut pending = PendingOutput::new(CliOutput {
            stdout: "synthetic private pending draft".into(),
            stderr: String::new(),
            exit_code: 0,
        });
        pending.wiped_on_drop = Some(wiped.clone());
        let result = finish_saved_read_output(pending, async {
            if store.generation() != generation {
                return Err(Error::Cancelled);
            }
            scope.check(&client)
        })
        .await;
        assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
        assert!(wiped.load(std::sync::atomic::Ordering::Acquire));
    }
    #[tokio::test]
    async fn direct_result_final_boundary_keeps_original_policy_child_and_store_fences() {
        use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
        for denial in ["original_gate","current_policy","caller","store"] {
            let directory=tempfile::tempdir().unwrap();
            let store=RuntimeStore::new(Some(directory.path().join("profile")),false).await.unwrap();
            let api="https://api.example.invalid";
            let session=openmates_sdk::Session{api_url:api.into(),session_id:"synthetic".into(),cookies:BTreeMap::new(),ws_token:None,master_key:Zeroizing::new([7;32]),hashed_email:"synthetic".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None};
            let mut client=Client::new(api,Some(session)).unwrap();
            let cancel=CancellationToken::new();client.set_operation_cancel(cancel.clone());
            let denied=Arc::new(AtomicBool::new(false));let observed=denied.clone();
            client.set_private_operation_gate(Some(Arc::new(move ||if observed.load(Ordering::Acquire){Err(Error::Forbidden)}else{Ok(())})));
            // Genuine restrictive core scope; the outer DTO is test-only and
            // can never produce a successful grant or authentic server result.
            let original=client.direct_app_skill_admission().unwrap();
            let admission=SavedReadOutputAdmission{api_url:api.into(),owner:"synthetic".into(),account_id:"synthetic".into(),team_id:None,store_generation:store.generation(),draft_scope:None,embed_share:None,app_scope:Some(original),full_read:None};
            client.set_private_operation_gate(Some(Arc::new(||Ok(()))));
            match denial {
                "original_gate"=>denied.store(true,Ordering::Release),
                "current_policy"=>client.set_privacy_options(openmates_sdk::privacy::PrivacyOptions{enhanced:true}),
                "caller"=>cancel.cancel(),
                "store"=>store.revoke().await.unwrap(),_=>unreachable!(),
            }
            let wiped=Arc::new(AtomicBool::new(false));
            let mut pending=PendingOutput::new(CliOutput{stdout:"synthetic private direct result".into(),stderr:String::new(),exit_code:0});
            pending.wiped_on_drop=Some(wiped.clone());
            let result=finish_saved_read_output(pending,persist_saved_read_final(&admission,&mut client,&store,None,&cancel)).await;
            assert!(matches!(result,Err(CliError::Client(_))),"{denial}");
            assert!(wiped.load(Ordering::Acquire),"{denial}");
        }
    }

    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[tokio::test(flavor="current_thread")]
    async fn actual_native_runtime_direct_apps_returns_original_json_without_saved_graph() {
        let (directory,api,peer)=final_fence_fixture_with_apps(None,true).await;
        let parsed=cli::parse_from(["openmates","--api-url",&api,"--state-dir",directory.path().to_str().unwrap(),"apps","code","get_docs","--input",r#"{"library":"React","question":"Synthetic docs?"}"#,"--json"]).unwrap();
        let output=tokio::time::timeout(Duration::from_secs(10),run(parsed.globals,parsed.invocation.unwrap())).await.unwrap().unwrap_or_else(|_| panic!("synthetic native direct app dispatch failed"));
        assert_eq!(output.exit_code,0);assert!(output.stderr.is_empty());
        assert_eq!(serde_json::from_str::<serde_json::Value>(&output.stdout).unwrap(),json!({"success":true,"credits_charged":0,"data":{"documentation":"Synthetic documentation"}}));
        assert!(peer.await.unwrap()>=3);
    }

}

#[cfg(test)]
#[path="command_runtime_full_read_tests.rs"]
mod full_read_final_tests;
