//! The terminal event loop never performs networking, key derivation or keyring IO.
use crate::Args;
use crossterm::{
    cursor::{Hide, Show},
    event::{
        DisableBracketedPaste, DisableMouseCapture, EnableBracketedPaste, EnableMouseCapture,
        Event, EventStream,
    },
    execute,
    terminal::{
        self, BeginSynchronizedUpdate, EndSynchronizedUpdate, EnterAlternateScreen,
        LeaveAlternateScreen,
    },
};
use futures_util::StreamExt;
use openmates::{
    client::{
        ChatFirstPageCandidate, ChatFirstPagePublication, ChatFirstPageSink, CacheSettlementPublication, CachedChatPublication, CachedChatViews, CachedChatWindow, ChatViewRead, CanonicalChatPublication,
        ChatInvalidation, ChatMonitor, ChatMonitorAccessDenial, ChatPublication,
        ChatRefreshDurableReceipt, Client, FreshChatInventory,
    },
    completion_recovery_adapter::{
        self, CanonicalRecoveryPersistence, CompletionRecoveryPumpOptions,
        CompletionRecoveryPumpOutcome,
    },
    error::{Error, Result},
    model::{Chat, Item, Message, Mutation, StreamUpdate, Workspace},
    runtime_store::{RuntimeStore, RuntimeStoreGeneration},
    storage::Session,
    ui::{Ui, UiCommand},
};
use ratatui::{Terminal, backend::CrosstermBackend};
use std::{
    io::{self, IsTerminal, Write},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{mpsc, watch};
use tokio_util::sync::CancellationToken;
use zeroize::{Zeroize, Zeroizing};

struct TerminalGuard {
    was_raw: bool,
}
impl TerminalGuard {
    fn enter() -> Result<Self> {
        let mut guard = Self {
            was_raw: terminal::is_raw_mode_enabled()?,
        };
        if let Err(error) = (|| -> io::Result<()> {
            terminal::enable_raw_mode()?;
            execute!(
                io::stdout(),
                EnterAlternateScreen,
                EnableBracketedPaste,
                EnableMouseCapture,
                Hide
            )
        })() {
            guard.restore();
            return Err(error.into());
        }
        Ok(guard)
    }
    fn restore(&mut self) {
        let _ = execute!(
            io::stdout(),
            EndSynchronizedUpdate,
            DisableMouseCapture,
            DisableBracketedPaste,
            Show,
            LeaveAlternateScreen
        );
        if !self.was_raw {
            let _ = terminal::disable_raw_mode();
        }
    }
}
impl Drop for TerminalGuard {
    fn drop(&mut self) {
        self.restore();
    }
}

// The UI receives only bounded immutable plaintext models and read-only guards,
// never the live Client, Store, Session, wrapping keys or effect authority.
#[derive(Clone)]
struct NativeCachedChatViews {
    views: std::sync::Arc<CachedChatViews>,
    store_generation: RuntimeStoreGeneration,
    security: u64,
}
struct NativeCachedChatPublication {
    publication: CachedChatPublication,
    store_generation: RuntimeStoreGeneration,
}
// Only Actor::authorized creates this after actual session/monitor admission
// and its durable save. The cached lane supplies negative lifecycle fencing,
// never the authentication authority which created this private publication.
struct NativeAuthPublication {
    owner: NativeCachedChatViews,
    request: CancellationToken,
    username: String,
    expires_at: Option<u64>,
}
impl NativeAuthPublication {
    fn into_auth(self) -> Result<(String, Option<u64>)> {
        if self.request.is_cancelled() || !self.owner.store_generation.is_current()
            || !self.owner.views.is_owner_current()
            || self.expires_at.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Cancelled);
        }
        Ok((self.username, self.expires_at))
    }
}
#[derive(Clone, Copy)]
enum MonitorAdmission { Ready, Offline, Denied(Error) }
struct NativeCacheSettlementPublication {
    publication: CacheSettlementPublication,
    store_generation: RuntimeStoreGeneration,
}
impl NativeCacheSettlementPublication {
    fn into_window(self) -> Result<CachedChatWindow> {
        if !self.store_generation.is_current() { return Err(Error::Cancelled); }
        let mut window = self.publication.into_window()?;
        if !self.store_generation.is_current() { window.zeroize(); return Err(Error::Cancelled); }
        Ok(window)
    }
}
struct NativeLivePublication {
    publication: ChatPublication,
    store_generation: RuntimeStoreGeneration,
    request: CancellationToken,
}
impl std::ops::Deref for NativeLivePublication {
    type Target = ChatPublication;
    fn deref(&self) -> &ChatPublication { &self.publication }
}
impl NativeLivePublication {
    fn into_models(self) -> Result<openmates::client::ChatModels> {
        if !self.store_generation.is_current() || self.request.is_cancelled() { return Err(Error::Cancelled); }
        let mut models = Zeroizing::new(self.publication.into_models()?);
        if !self.store_generation.is_current() || self.request.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(std::mem::replace(&mut *models, openmates::client::ChatModels {
            items: vec![], selection: openmates::client::ChatSelectionUpdate::Unchanged,
        }))
    }
}
struct NativeCanonicalChatPublication {
    publication: CanonicalChatPublication,
    store_generation: RuntimeStoreGeneration,
}
impl NativeCanonicalChatPublication {
    fn into_chat(self) -> Result<Chat> {
        if !self.store_generation.is_current() { return Err(Error::Cancelled); }
        let chat = self.publication.into_chat()?;
        if !self.store_generation.is_current() {
            let mut rejected = CachedChatWindow { chat, has_more_before: None,
                history_complete: false, cached: false, refreshing: false, pii_restoration: "page_local" };
            rejected.zeroize();
            return Err(Error::Cancelled);
        }
        Ok(chat)
    }
}
impl NativeCachedChatViews {
    fn publish(&self, id: &str, epoch: Stamp, cancel: CancellationToken) -> Result<Option<Reply>> {
        if self.security != epoch.security || !self.store_generation.is_current() {
            return Err(Error::Cancelled);
        }
        let Some(publication) = self.views.publish(id, cancel)? else { return Ok(None); };
        if !self.store_generation.is_current() { return Err(Error::Cancelled); }
        Ok(Some(Reply { epoch, view: View::CachedChat(NativeCachedChatPublication {
            publication, store_generation: self.store_generation.clone(),
        }) }))
    }
}
impl NativeCachedChatPublication {
    fn into_window(self) -> Result<CachedChatWindow> {
        if !self.store_generation.is_current() { return Err(Error::Cancelled); }
        let mut window = self.publication.into_window()?;
        if !self.store_generation.is_current() { window.zeroize(); return Err(Error::Cancelled); }
        Ok(window)
    }
}
fn close_cached_views(receiver: &watch::Receiver<Option<NativeCachedChatViews>>) {
    let current = receiver.borrow().clone();
    if let Some(current) = current { current.views.close(); }
}
fn apply_cached_chat(ui: &mut Ui, publication: NativeCachedChatPublication) {
    // Optional cache display never suppresses the queued canonical read. An old
    // owner/lifetime/generation is simply ineligible for this immediate preview.
    if let Ok(window) = publication.into_window() {
        ui.set_cached_chat(window.chat);
    }
}

fn apply_canonical_chat(ui: &mut Ui, publication: NativeCanonicalChatPublication) {
    if let Ok(chat) = publication.into_chat() { ui.set_chat(chat); }
    else { ui.hide_cached_chat(); }
}

fn apply_cached_chat_offline(ui: &mut Ui, publication: NativeCachedChatPublication) {
    if let Ok(window) = publication.into_window() {
        ui.set_cached_chat_offline(window.chat);
    }
}

struct NativeChatFirstPagePublication {
    publication: ChatFirstPagePublication,
    store_generation: RuntimeStoreGeneration,
}
impl NativeChatFirstPagePublication {
    fn into_window(self) -> Result<CachedChatWindow> {
        if !self.store_generation.is_current() { return Err(Error::Cancelled); }
        let mut window = self.publication.into_window()?;
        if !self.store_generation.is_current() { window.zeroize(); return Err(Error::Cancelled); }
        Ok(window)
    }
}
struct NativeChatFirstPageSink {
    store: RuntimeStore,
    generation: RuntimeStoreGeneration,
    passphrase: Option<Zeroizing<String>>,
    replies: mpsc::Sender<Reply>,
    epoch: Stamp,
}
impl ChatFirstPageSink for NativeChatFirstPageSink {
    fn admit_checkpoint<'a>(&'a mut self, _client: &'a Client, checkpoint_json_bytes: usize)
        -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<bool>> + Send + 'a>>
    {
        Box::pin(async move {
            if !self.generation.is_current() { return Err(Error::Cancelled); }
            let accepted = self.store.admits_ciphertext_checkpoint(checkpoint_json_bytes)?;
            if !self.generation.is_current() { return Err(Error::Cancelled); }
            Ok(accepted)
        })
    }
    fn first_page<'a>(&'a mut self, client: &'a mut Client, candidate: ChatFirstPageCandidate)
        -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>>
    {
        Box::pin(async move {
            if !self.generation.is_current() { return Err(Error::Cancelled); }
            let receipt = ChatRefreshDurableReceipt {
                ciphertext_sha256: candidate.ciphertext_sha256()?,
                credential_revision: candidate.credential_revision(),
            };
            openmates::session_runtime::persist(client, &self.store, self.passphrase.clone()).await?;
            if !self.generation.is_current() { return Err(Error::Cancelled); }
            let publication = client.commit_chat_first_page(candidate, receipt)?;
            self.replies.send(Reply { epoch: self.epoch, view: View::ChatFirstPage(NativeChatFirstPagePublication {
                publication, store_generation: self.generation.clone(),
            }) }).await.map_err(|_| Error::Cancelled)
        })
    }
}
enum View {
    AdmittedAuth(NativeAuthPublication),
    #[cfg(test)]
    Auth {
        username: String,
        expires_at: Option<u64>,
    },
    SignedOut,
    Unlock,
    Items(Workspace, Vec<Item>),
    Chat(Chat),
    CanonicalChat(NativeCanonicalChatPublication),
    CacheSettled(NativeCacheSettlementPublication),
    ChatFirstPage(NativeChatFirstPagePublication),
    CachedChat(NativeCachedChatPublication),
    CachedChatOffline(NativeCachedChatPublication),
    ChatOpenFailed(Error),
    Sent(Chat),
    Monitor(Error, CancellationToken),
    Live(NativeLivePublication),
    AccessDenied(ChatMonitorAccessDenial, CancellationToken),
    Item(Workspace, Item),
    Stream(StreamUpdate),
    PairUri(String),
    PairPin,
    Share(String),
    MutationSucceeded,
    Status(&'static str),
    Failed(Error),
    Done,
}
#[derive(Clone, Copy, Default, PartialEq, Eq)]
struct Stamp {
    security: u64,
    view: u64,
}
// One opportunistic cached paint for an admitted Open that had no reader yet.
// This stores selectors/lifetime only; SDK publications retain actual authority.
struct PendingCachedSelection { id:String,epoch:Stamp,request:CancellationToken }
impl PendingCachedSelection {
    fn is_current(&self,current:Stamp,authenticated:bool)->bool {authenticated&&self.epoch==current&&!self.request.is_cancelled()}
    fn is_completed_by(&self,reply:&Reply)->bool {
        // Any accepted global denial/error closes the opportunity. Successful
        // view completion must match this exact selection, never a Boot Done.
        match &reply.view {
            View::SignedOut|View::Failed(_)|View::ChatOpenFailed(Error::Expired|Error::Authentication|Error::Forbidden)=>return true,
            View::AccessDenied(_,lifetime)=>return !lifetime.is_cancelled(),
            View::Monitor(Error::Expired|Error::Authentication|Error::Forbidden,lifetime)=>return !lifetime.is_cancelled(),
            _=>{},
        }
        self.epoch==reply.epoch&&matches!(&reply.view,View::Chat(_)|View::CanonicalChat(_)|View::CacheSettled(_)|View::CachedChatOffline(_)|View::ChatOpenFailed(_)|View::Sent(_)|View::Item(..)|View::MutationSucceeded|View::Done)
    }
}
struct Reply {
    epoch: Stamp,
    view: View,
}
impl Stamp {
    fn accepts(self, reply: &Reply) -> bool {
        let view_bound = match &reply.view {
            View::ChatOpenFailed(Error::Expired | Error::Authentication | Error::Forbidden) => false,
            View::Chat(_) | View::CanonicalChat(_) | View::CacheSettled(_) | View::ChatFirstPage(_) | View::CachedChat(_) | View::CachedChatOffline(_)
                | View::ChatOpenFailed(_) | View::Item(..) | View::Share(_) | View::MutationSucceeded => true,
            _ => false,
        };
        reply.epoch.security == self.security && (reply.epoch.view == self.view || !view_bound)
    }
}
enum Work {
    Boot,
    /// The slow part of boot (global recovery + list). Runs only when the
    /// request queue is idle and yields to a chat Open/Send (preempted).
    BootSync,
    Command(UiCommand),
    PairPoll,
    Monitor,
    Live,
}
type BootSyncPreempt = std::sync::Arc<std::sync::Mutex<Option<CancellationToken>>>;
fn preempt_boot_sync(slot: &BootSyncPreempt) {
    if let Some(token) = slot.lock().ok().and_then(|mut slot| slot.take()) {
        token.cancel();
    }
}
struct Request {
    epoch: Stamp,
    work: Work,
    cancel: CancellationToken,
}

pub async fn run(args: Args) -> Result<()> {
    if !io::stdin().is_terminal() || !io::stdout().is_terminal() {
        return Err(Error::Invalid(
            "Run this application in an interactive terminal.",
        ));
    }
    // A panic restores the terminal without writing panic payloads/private data.
    let previous_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {
        let _ = execute!(
            io::stdout(),
            EndSynchronizedUpdate,
            DisableMouseCapture,
            DisableBracketedPaste,
            Show,
            LeaveAlternateScreen
        );
        let _ = terminal::disable_raw_mode();
    }));
    let result = run_terminal(args).await;
    std::panic::set_hook(previous_hook);
    result
}

async fn run_terminal(args: Args) -> Result<()> {
    let _guard = TerminalGuard::enter()?;
    let mut terminal = Terminal::new(CrosstermBackend::new(io::stdout()))?;
    // Clear the fresh alternate screen directly. ratatui's `Terminal::clear`
    // first asks the terminal for the cursor position (DSR), which adds a
    // round trip before the first frame and fails startup after crossterm's
    // 2 s timeout on terminals that never answer it. The new Terminal's empty
    // back buffer already forces a complete first draw.
    execute!(terminal.backend_mut(), terminal::Clear(terminal::ClearType::All))?;
    let mut ui = if args.demo {
        Ui::demo(20, 25)
    } else {
        // Boot decides: a stored session paints cached cards at once and an
        // early Enter must open one; SignedOut/Unlock replies show the forms.
        // An invisible login form would otherwise swallow those first keys.
        Ui::new()
    };
    let mut epoch = Stamp::default();
    let mut active = CancellationToken::new();
    let (requests, receiver) = mpsc::channel(32);
    let (priority, controls) = mpsc::unbounded_channel();
    let (consent, decisions) = mpsc::unbounded_channel();
    let (replies, mut updates) = mpsc::channel(128);
    let (cached_sender, mut cached_views) = watch::channel(None::<NativeCachedChatViews>);
    let stop = CancellationToken::new();
    let demo = args.demo;
    // Cancels a running background BootSync so a chat Open/Send runs first.
    let boot_sync_preempt: BootSyncPreempt = Default::default();
    let actor_preempt = boot_sync_preempt.clone();
    let worker = if demo {
        None
    } else {
        let shutdown = stop.clone();
        Some(tokio::spawn(async move {
            actor(args, receiver, controls, decisions, replies, cached_sender, shutdown, actor_preempt).await
        }))
    };
    if !demo {
        requests
            .send(Request {
                epoch,
                work: Work::Boot,
                cancel: active.clone(),
            })
            .await
            .map_err(|_| Error::Io)?;
    }
    let mut events = EventStream::new();
    let mut render_tick = tokio::time::interval(Duration::from_millis(16));
    render_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut auth_tick = tokio::time::interval(Duration::from_secs(2));
    auth_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut dirty = true;
    let mut painted = false;
    let mut pairing = false;
    let mut pair_poll_pending = false;
    let mut expires_at: Option<u64> = None;
    let mut authenticated = false;
    let mut monitor_retry = None;
    let mut membership_check = None;
    let mut clipboard = None;
    let mut pending_cached_selection:Option<PendingCachedSelection>=None;
    let mut cached_channel_open=true;
    let interrupt = tokio::signal::ctrl_c();
    tokio::pin!(interrupt);
    #[cfg(unix)]
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    #[cfg(unix)]
    let mut hangup = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::hangup())?;
    'application: loop {
        let commands = tokio::select! {
            _ = &mut interrupt => break,
            _ = async {
                if let Some(deadline)=expires_at {tokio::time::sleep(Duration::from_millis(deadline.saturating_sub(now_ms()))).await;}
                else {std::future::pending::<()>().await;}
            }, if !demo => {
                pending_cached_selection=None;
                close_cached_views(&cached_views);
                authenticated=false;expires_at=None;ui.clear_private();ui.set_error(&Error::Expired.to_string());
                vec![UiCommand::Logout]
            },
            _ = async { #[cfg(unix)] { terminate.recv().await; } #[cfg(not(unix))] { std::future::pending::<()>().await; } } => break,
            _ = async { #[cfg(unix)] { hangup.recv().await; } #[cfg(not(unix))] { std::future::pending::<()>().await; } } => break,
            // Idle terminals have no paint deadline. Resume the existing frame
            // limiter only when input or a client update changes the view.
            _ = render_tick.tick(), if dirty => {
                if dirty {
                    execute!(terminal.backend_mut(), BeginSynchronizedUpdate)?;
                    let painted_result = terminal.draw(|frame| ui.draw(frame)).map(|_|());
                    let ended = execute!(terminal.backend_mut(), EndSynchronizedUpdate);
                    painted_result?; ended?;
                    terminal.backend_mut().flush()?;
                    dirty=false; painted=true;
                }
                Vec::new()
            },
            _ = auth_tick.tick(), if !demo => {
                if expires_at.is_some_and(|deadline| deadline <= now_ms()) {
                    ui.clear_private(); ui.set_error(&Error::Expired.to_string()); expires_at=None;
                    vec![UiCommand::Logout]
                } else {
                    if (monitor_retry.is_some_and(|due|tokio::time::Instant::now()>=due)||membership_check.is_some_and(|due|tokio::time::Instant::now()>=due))
                        && requests.try_send(Request{epoch,work:Work::Monitor,cancel:active.clone()}).is_ok(){monitor_retry=None;membership_check=Some(tokio::time::Instant::now()+Duration::from_secs(30));}
                    if pairing && !pair_poll_pending {
                        pair_poll_pending = requests.try_send(Request { epoch, work: Work::PairPoll, cancel: active.clone() }).is_ok();
                    }
                    Vec::new()
                }
            },
            changed=cached_views.changed(),if !demo&&cached_channel_open=>{
                if changed.is_err(){cached_channel_open=false;}
                else {
                    let current=cached_views.borrow_and_update().clone();
                    if pending_cached_selection.as_ref().is_some_and(|selection|!selection.is_current(epoch,authenticated)){pending_cached_selection=None;}
                    if let (Some(selection),Some(current))=(pending_cached_selection.as_ref(),current) {
                        if let Ok(Some(reply))=current.publish(&selection.id,selection.epoch,selection.request.clone()) {
                            // Disarm BEFORE consuming the opaque publication;
                            // no late watch update can demote canonical content.
                            pending_cached_selection=None;
                            if epoch.accepts(&reply)&&let View::CachedChat(publication)=reply.view {apply_cached_chat(&mut ui,publication);dirty=true;}
                        }
                    }
                }
                Vec::new()
            },
            reply = updates.recv(), if !demo => {
                let Some(reply)=reply else { return Err(Error::Io) };
                if !epoch.accepts(&reply){continue}
                if pending_cached_selection.as_ref().is_some_and(|selection|selection.is_completed_by(&reply)){pending_cached_selection=None;}
                let mut effects=Vec::new();
                match reply.view {
                    View::AdmittedAuth(publication)=>{
                        let Ok((username,deadline))=publication.into_auth() else { continue; };
                        authenticated=true;ui.set_authenticated(true);ui.set_username(&username);expires_at=deadline;pairing=false;membership_check=Some(tokio::time::Instant::now()+Duration::from_secs(30));ui.set_status("Signed in · native encrypted session");
                    },
                    #[cfg(test)]
                    View::Auth{username,expires_at:deadline}=>{authenticated=true;ui.set_authenticated(true);ui.set_username(&username);expires_at=deadline;pairing=false;membership_check=Some(tokio::time::Instant::now()+Duration::from_secs(30));ui.set_status("Signed in · native encrypted session");},
                    View::SignedOut=>{close_cached_views(&cached_views);authenticated=false;ui.clear_private();ui.set_authenticated(false);ui.set_status("Signed out");expires_at=None;pairing=false;monitor_retry=None;membership_check=None;},
                    View::Unlock=>ui.set_unlock_required(true),
                    View::Items(workspace,items)=>ui.set_items(workspace,items),
                    View::Chat(chat)=>ui.set_chat(chat),
                    View::CanonicalChat(publication)=>apply_canonical_chat(&mut ui,publication),
                    View::CacheSettled(publication)=>{
                        if let Ok(window)=publication.into_window(){ui.set_settled_chat(window.chat);}
                        else {ui.hide_cached_chat();}
                    },
                    View::ChatFirstPage(publication)=>{
                        // Disarm opportunistic old-cache paint before accepting
                        // the fresh first page. This remains read-only/loading.
                        pending_cached_selection=None;
                        if let Ok(window)=publication.into_window(){ui.set_cached_chat(window.chat);}
                        else {ui.hide_cached_chat();}
                    },
                    View::CachedChat(publication)=>apply_cached_chat(&mut ui, publication),
                    View::CachedChatOffline(publication)=>apply_cached_chat_offline(&mut ui, publication),
                    View::Sent(chat)=>{ui.send_succeeded();if reply.epoch.view==epoch.view{ui.set_chat(chat);}},
                    View::Live(publication)=>{
                        // A force-logout/revocation may arrive while the durable
                        // actor reply waits in this bounded channel.
                        if let Ok(models)=publication.into_models(){ui.apply_live_chat_models(models);}
                    },
                    View::AccessDenied(denial,lifetime)=>{
                        if lifetime.is_cancelled(){continue}
                        match denial {
                            ChatMonitorAccessDenial::Expired|ChatMonitorAccessDenial::ScopeRevoked=>{
                                close_cached_views(&cached_views);
                                authenticated=false;ui.clear_private();ui.set_error("Session or selected Team access was revoked.");effects.push(UiCommand::Logout);
                            },
                            ChatMonitorAccessDenial::ChatUnavailable{chat_id}=>{
                                close_cached_views(&cached_views);
                                ui.hide_live_chat(&chat_id);monitor_retry=Some(tokio::time::Instant::now()+Duration::from_secs(3));
                            },
                        }
                    },
                    View::Monitor(error,lifetime)=>{
                        if lifetime.is_cancelled(){continue}
                        if matches!(error,Error::Expired|Error::Forbidden){close_cached_views(&cached_views);authenticated=false;ui.clear_private();ui.set_error(&error.to_string());effects.push(UiCommand::Logout);}
                        else{ui.mark_cached_chat_offline();ui.set_status("Offline · reconnecting…");monitor_retry=Some(tokio::time::Instant::now()+Duration::from_secs(3));}
                    },
                    View::Item(workspace,item)=>ui.set_item(workspace,item),
                    View::Stream(update)=>{if reply.epoch.view==epoch.view{ui.stream(update)}else{ui.background_stream(update)}},
                    View::PairUri(uri)=>{pairing=true;ui.set_pairing(&uri);},
                    View::PairPin=>ui.set_pair_pin_required(),
                    View::Share(uri)=>ui.set_share_url(&uri),
                    View::MutationSucceeded=>ui.mutation_succeeded(),
                    View::Status(message)=>ui.set_status(message),
                    View::Failed(error)|View::ChatOpenFailed(error)=>{
                        if matches!(error,Error::Unavailable{code:"completion_recovery_checkpoint_invalid",..}) {
                            ui.set_error("Local completion checkpoint is invalid; encrypted data was preserved.");
                        } else {ui.set_error(&error.to_string());}
                        if matches!(error,Error::Expired|Error::Authentication|Error::Forbidden){pairing=false}
                    },
                    View::Done=>{ui.set_busy(false);pair_poll_pending=false;},
                }
                dirty=true;
                effects
            },
            event = events.next() => {
                let event = match event { Some(Ok(event))=>event,Some(Err(_))=>return Err(Error::Io),None=>break };
                dirty=true;
                match event {
                    Event::Key(key)=>ui.key(key),
                    Event::Paste(text)=>ui.paste(&text),
                    Event::Mouse(mouse) if painted=>ui.mouse(mouse),
                    Event::Resize(width,height)=>{ui.resize(width,height);painted=false;Vec::new()},
                    _=>Vec::new(),
                }
            }
        };
        for command in commands {
            match command {
                UiCommand::Quit => break 'application,
                UiCommand::Consent {
                    request_id,
                    approved_ids,
                } => {
                    if consent.send((request_id, approved_ids)).is_err() {
                        ui.set_error("The consent request has ended.");
                    }
                }
                UiCommand::SelectionMode(selecting) => {
                    if selecting {
                        execute!(terminal.backend_mut(), DisableMouseCapture)?;
                    } else {
                        execute!(terminal.backend_mut(), EnableMouseCapture)?;
                    }
                }
                UiCommand::Copy(text) => {
                    // Explicit user action only. Never print clipboard data to logs.
                    if clipboard.is_none() {
                        clipboard = arboard::Clipboard::new().ok();
                    }
                    if clipboard
                        .as_mut()
                        .is_none_or(|clipboard| clipboard.set_text(text).is_err())
                    {
                        ui.set_error("The clipboard is unavailable.");
                    }
                }
                UiCommand::OpenUrl(uri) => {
                    let valid = url::Url::parse(&uri).ok().filter(|url| {
                        matches!(url.scheme(), "https" | "http")
                            && url.username().is_empty()
                            && url.password().is_none()
                    });
                    if valid.is_none() || webbrowser::open(&uri).is_err() {
                        ui.set_error("This link could not be opened.");
                    }
                }
                command if demo => demo_command(&mut ui, command),
                UiCommand::Cancel => {
                    ui.hide_cached_chat();
                    active.cancel();
                    active = CancellationToken::new();
                    if !authenticated {
                        epoch.security = epoch.security.wrapping_add(1);
                    }
                    epoch.view = epoch.view.wrapping_add(1);
                    pair_poll_pending = false;
                    ui.set_busy(false);
                    ui.set_status("Cancelling…");
                    pairing = false;
                    let _ = priority.send(Request {
                        epoch,
                        work: Work::Command(UiCommand::Cancel),
                        cancel: active.clone(),
                    });
                }
                command => {
                    if authenticated
                        && matches!(command, UiCommand::Login { .. } | UiCommand::BeginPair)
                    {
                        ui.set_error("Sign out before signing in to another account.");
                        continue;
                    }
                    if matches!(
                        command,
                        UiCommand::Open(..) | UiCommand::Refresh(_) | UiCommand::Send { .. }
                    ) {
                        epoch.view = epoch.view.wrapping_add(1);
                    }
                    if matches!(command, UiCommand::Open(Workspace::Chats, _) | UiCommand::Send { .. }) {
                        preempt_boot_sync(&boot_sync_preempt);
                    }
                    if matches!(
                        command,
                        UiCommand::Logout
                            | UiCommand::SwitchTeam(_)
                            | UiCommand::Login { .. }
                            | UiCommand::BeginPair
                            | UiCommand::Unlock { .. }
                    ) {
                        close_cached_views(&cached_views);
                        active.cancel();
                        active = CancellationToken::new();
                        epoch.security = epoch.security.wrapping_add(1);
                        epoch.view = epoch.view.wrapping_add(1);
                        pair_poll_pending = false;
                        if matches!(command, UiCommand::Logout | UiCommand::SwitchTeam(_)) {
                            authenticated = false;
                            ui.clear_private();
                            expires_at = None;
                            membership_check = None;
                            monitor_retry = None;
                        }
                    }
                    // Consume cached data synchronously BEFORE enqueuing the
                    // canonical Open. This lane does not borrow or wait for the
                    // actor, so in-flight background reads cannot delay first
                    // content. Nothing async can later demote a canonical view.
                    pending_cached_selection=None;
                    if let UiCommand::Open(Workspace::Chats, id) = &command {
                        if authenticated {pending_cached_selection=Some(PendingCachedSelection{id:id.clone(),epoch,request:active.clone()});}
                        ui.hide_cached_chat();
                        let cached = cached_views.borrow().clone();
                        if authenticated && let Some(cached) = cached {
                            if let Ok(Some(reply)) = cached.publish(id, epoch, active.clone()) {
                                pending_cached_selection=None;
                                if epoch.accepts(&reply) && let View::CachedChat(publication) = reply.view {
                                    apply_cached_chat(&mut ui, publication);
                                }
                            }
                        }
                    }
                    ui.set_busy(true);
                    let critical = matches!(command, UiCommand::Logout | UiCommand::SwitchTeam(_));
                    let request = Request {
                        epoch,
                        work: Work::Command(command),
                        cancel: active.clone(),
                    };
                    let delivered = if critical {
                        priority.send(request).is_ok()
                    } else {
                        requests.try_send(request).is_ok()
                    };
                    if !delivered {
                        pending_cached_selection=None;
                        ui.set_error("The client is busy. Cancel the current operation and retry.");
                    }
                }
            }
            dirty = true;
        }
    }
    close_cached_views(&cached_views);
    active.cancel();
    stop.cancel();
    drop(requests);
    drop(priority);
    drop(consent);
    // Restore terminal immediately; a bounded best effort lets cancellation persist
    // an already admitted turn without leaving raw mode active during network IO.
    drop(terminal);
    drop(_guard);
    if let Some(worker) = worker {
        let _ = tokio::time::timeout(Duration::from_secs(5), worker).await;
    }
    Ok(())
}

fn demo_command(ui: &mut Ui, command: UiCommand) {
    match command {
        UiCommand::Refresh(workspace) => ui.demo_refresh(workspace),
        UiCommand::Open(workspace, id) => ui.demo_open(workspace, &id),
        UiCommand::Send { chat_id, text } => ui.set_chat(Chat {
            id: chat_id.unwrap_or_else(|| "demo".into()),
            title: "Native Rust presentation demo".into(),
            category: "demo".into(),
            messages: vec![
                Message {
                    id: "demo-user".into(),
                    role: "user".into(),
                    content: text,
                    ..Message::default()
                },
                Message {
                    id: "demo-assistant".into(),
                    role: "assistant".into(),
                    content: "Synthetic local reply. The demo performs no network requests.".into(),
                    ..Message::default()
                },
            ],
        }),
        _ => ui.set_status("Synthetic demo · this action requires a signed-in account"),
    }
}

// Explicit application foreground grant; never survives a dropped/canceled
// pump or admission future. No inference or Send/mutation replay occurs here.
struct ForegroundRecoveryGrant<'a>(&'a mut Client);
impl<'a> ForegroundRecoveryGrant<'a> {
    fn new(client: &'a mut Client) -> Result<Self> {
        client.set_foreground_completion_recovery(true)?;
        Ok(Self(client))
    }
}
impl std::ops::Deref for ForegroundRecoveryGrant<'_> {
    type Target = Client;
    fn deref(&self) -> &Client {
        self.0
    }
}
impl std::ops::DerefMut for ForegroundRecoveryGrant<'_> {
    fn deref_mut(&mut self) -> &mut Client {
        self.0
    }
}
impl Drop for ForegroundRecoveryGrant<'_> {
    fn drop(&mut self) {
        let _ = self.0.set_foreground_completion_recovery(false);
    }
}
// Explicit native account/context binding. No Debug/serde or ambient profile.
struct RecoveryPersistence {
    store: RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    generation: u64,
    api: String,
    owner_hash: String,
    owner_id: String,
    team: Option<String>,
    master: Zeroizing<[u8; 32]>,
}
impl RecoveryPersistence {
    fn new(actor: &Actor) -> Result<Self> {
        let session = actor.client.session().ok_or(Error::Authentication)?;
        let owner = ["id", "user_id"]
            .into_iter()
            .filter_map(|key| actor.client.user()[key].as_str())
            .find(|owner| !owner.is_empty())
            .ok_or(Error::Authentication)?;
        Ok(Self {
            store: actor.store.clone(),
            passphrase: actor.passphrase.clone(),
            generation: actor.store.generation(),
            api: session.api_url.clone(),
            owner_hash: session.hashed_email.clone(),
            owner_id: owner.to_owned(),
            team: session.active_team_id.clone(),
            master: session.master_key.clone(),
        })
    }
    fn check(&self, client: &Client, cancel: &CancellationToken) -> Result<()> {
        if cancel.is_cancelled() || self.store.generation() != self.generation {
            return Err(Error::Cancelled);
        }
        let session = client.session().ok_or(Error::Expired)?;
        if session
            .paired_session_expires_at
            .is_some_and(|at| at <= now_ms())
        {
            return Err(Error::Expired);
        }
        let owner = ["id", "user_id"]
            .into_iter()
            .filter_map(|key| client.user()[key].as_str())
            .find(|id| !id.is_empty());
        if session.api_url != self.api
            || session.hashed_email != self.owner_hash
            || session.active_team_id != self.team
            || owner != Some(self.owner_id.as_str())
            || session.master_key[..] != self.master[..]
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
impl CanonicalRecoveryPersistence for RecoveryPersistence {
    fn persist_reconciled_canonical<'a>(
        &'a mut self,
        client: &'a mut Client,
        _chat_id: &'a str,
        cancel: &'a CancellationToken,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>> {
        Box::pin(async move {
            self.check(client, cancel)?;
            // Core commit/resume already strictly reread exact canonical
            // ciphertext. Do not substitute public open_chat's offline fallback.
            openmates::session_runtime::persist(
                client,
                &self.store,
                self.passphrase.clone(),
            )
            .await?;
            self.check(client, cancel)
        })
    }
}
struct Actor {
    client: Client,
    store: RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    pair_phase: u8,
    relay: Option<tokio::task::JoinHandle<()>>,
    explicit_api: Option<String>,
    explicit_app: Option<String>,
    installed_app: Option<(String, String)>,
    trusted_path: Option<std::path::PathBuf>,
    trusted_verified: bool,
    live_monitor: Option<ChatMonitor>,
    // Retained across dropped/canceled read futures; cleared only after
    // publication or selected-instance/context invalidation.
    live_pending: Option<ChatInvalidation>,
    live_lifetime: Option<CancellationToken>,
    live_epoch: Stamp,
    live_cancel: CancellationToken,
    live_retry_at: Option<tokio::time::Instant>,
    live_selected: Option<String>,
    // Root merges the explicit foreground recovery-pump adapter at this seam.
    // These bounded IDs grant no claim/lease and are never interpreted by UI.
    recovery_hints: std::collections::BTreeSet<String>,
    recovery_start_needed: bool,
    recovery_blocked: bool,
    recovery_retry_at: Option<tokio::time::Instant>,
    last_live_hint: Option<ChatInvalidation>,
    cached_views: watch::Sender<Option<NativeCachedChatViews>>,
    cached_views_blocked: bool,
}
async fn actor(
    args: Args,
    mut requests: mpsc::Receiver<Request>,
    controls: mpsc::UnboundedReceiver<Request>,
    decisions: mpsc::UnboundedReceiver<(String, Vec<String>)>,
    replies: mpsc::Sender<Reply>,
    cached_views: watch::Sender<Option<NativeCachedChatViews>>,
    stop: CancellationToken,
    boot_sync_preempt: BootSyncPreempt,
) {
    let initial = async {
        let directories = directories::BaseDirs::new().ok_or(Error::Io)?;
        let profile = openmates::profile::resolve(
            openmates::profile::ProfileOptions {
                profile: args.profile,
                state_dir: args.state_dir,
                api_url: args.api_url,
            },
            openmates::profile::ProfileEnvironment::capture(),
            directories.home_dir(),
        )?;
        let installed_api = openmates::server::installed_api(&profile.state_dir)?;
        let installed_app = openmates::server::installed_app(&profile.state_dir)?;
        let explicit_app = std::env::var("OPENMATES_APP_URL")
            .ok()
            .filter(|s| !s.is_empty());
        let api = profile.api_url(None, installed_api.as_deref())?;
        let mut client = Client::new(&api, None)?;
        client.set_identity(openmates_sdk::ClientIdentity::Cli);
        client.set_interactive(true);
        client.set_app_origin(openmates::profile::application_origin(
            &api,
            explicit_app.clone(),
            installed_api.as_deref(),
            installed_app.clone(),
        )?)?;
        client.set_private_operation_gate(Some(openmates::privacy::gate_for_profile(
            &profile,
            directories.home_dir(),
        )));
        let trusted_path = openmates::cli::trusted_account::enforced_profile(
            &profile.state_dir,
            args.trusted_account,
        )
        .map_err(|_| Error::Forbidden)?;
        Ok::<_, Error>(Actor {
            client,
            trusted_path,
            trusted_verified: false,
            live_monitor: None,
            live_pending: None,
            live_lifetime: None,
            live_epoch: Stamp::default(),
            live_cancel: CancellationToken::new(),
            live_retry_at: None,
            live_selected: None,
            recovery_hints: Default::default(),
            recovery_start_needed: true,
            recovery_blocked: false,
            recovery_retry_at: None,
            last_live_hint: None,
            cached_views,
            cached_views_blocked: false,
            store: RuntimeStore::new(Some(profile.state_dir), args.encrypted_vault).await?,
            passphrase: None,
            pair_phase: 0,
            relay: None,
            explicit_api: profile.api_url_override,
            explicit_app,
            installed_app: installed_api.zip(installed_app),
        })
    }
    .await;
    let mut state = match initial {
        Ok(state) => state,
        Err(error) => {
            let _ = replies
                .send(Reply {
                    epoch: Stamp::default(),
                    view: View::Failed(error),
                })
                .await;
            return;
        }
    };
    let mut controls = fenced_controls(controls, state.store.clone(), replies.clone());
    state.client.set_consent_receiver(decisions);
    // Mailbox tick performs no network on an idle connection. Reads remain in
    // the keyless SDK task; control/request work always wins actor admission.
    let mut live_tick = tokio::time::interval(Duration::from_millis(250));
    live_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut boot_sync: Option<Stamp> = None;
    while let Some(request) = tokio::select! {
        biased;
        _=stop.cancelled()=>None,
        request=controls.recv()=>request,
        request=requests.recv()=>request,
        // Only when no command is queued: a chat Open never waits behind it.
        _=std::future::ready(()), if boot_sync.is_some() => {
            let token = CancellationToken::new();
            if let Ok(mut slot) = boot_sync_preempt.lock() { *slot = Some(token.clone()); }
            boot_sync.take().map(|epoch| Request { epoch, work: Work::BootSync, cancel: token })
        },
        _=live_tick.tick(), if state.live_monitor.as_ref().is_some_and(|m|m.is_valid()) && !state.live_cancel.is_cancelled()
            =>Some(Request{epoch:state.live_epoch,work:Work::Live,cancel:state.live_cancel.clone()}),
    } {
        let background = matches!(&request.work, Work::Live);
        let booting = matches!(&request.work, Work::Boot);
        let syncing = matches!(&request.work, Work::BootSync);
        let opening_chat = matches!(&request.work, Work::Command(UiCommand::Open(Workspace::Chats, _)));
        let epoch = request.epoch;
        let cancel = request.cancel.clone();
        let mut result = state.dispatch(request, &replies).await;
        if syncing {
            if let Ok(mut slot) = boot_sync_preempt.lock() { slot.take(); }
            // A preempted background sync resumes once the queue is idle again.
            if result == Err(Error::Cancelled) && cancel.is_cancelled() && state.client.session().is_some() {
                boot_sync = Some(epoch);
                continue;
            }
        }
        if booting && result.is_ok() && state.client.session().is_some() {
            boot_sync = Some(epoch);
        }
        if result.is_err() {
            // Retire this optional presentation on every failed read. Known
            // auth/access denial keeps it closed until a new monitor owner
            // lifetime is admitted; other failures retain canonical recovery.
            if matches!(result, Err(Error::Expired | Error::Authentication | Error::Forbidden)) {
                state.cached_views_blocked = true;
            }
            if state.cached_views_blocked { state.retire_cached_views(); }
        } else if !background {
            state.stage_cached_views(epoch);
        }
        // Even if cancellation dropped a stalled protocol future, its queued
        // Submitted/Admitted fences must reach the UI before a failure restores text.
        if let Some(relay) = state.relay.as_mut() {
            let _ = relay.await;
        }
        state.relay = None;
        if result.is_err()
            && result != Err(Error::Expired)
            && state.client.session().is_some()
            && state.pair_phase == 0
        {
            // A later request can fail after an earlier refresh rotated its cookie.
            // A native keyring may never answer. Once a security command has
            // cancelled this request, leave its started write ordered in Store
            // and admit the priority command, whose durable fence prevents that
            // old write from publishing after logout.
            if let Err(storage_error) =
                finish_or_cancel(state.persist(), &cancel, Duration::from_secs(2)).await
            {
                result = Err(storage_error);
            }
        }
        if let Err(mut error) = result {
            if matches!(error, Error::Expired) {
                state.passphrase = None;
                state.pair_phase = 0;
                let _ = replies
                    .send(Reply {
                        epoch,
                        view: View::SignedOut,
                    })
                    .await;
                let cleanup = state.store.clear().await;
                let _ = state.client.logout().await;
                if let Err(cleanup_error) = cleanup {
                    error = cleanup_error;
                }
            }
            let _ = replies
                .send(Reply {
                    epoch,
                    view: if opening_chat { View::ChatOpenFailed(error) } else { View::Failed(error) },
                })
                .await;
        }
        if !background {
            let _ = replies
                .send(Reply {
                    epoch,
                    view: View::Done,
                })
                .await;
        }
    }
    state.retire_cached_views();
    state.live_monitor.take();
    if let Some(lifetime) = state.live_lifetime.take() {
        lifetime.cancel();
    }
}

/// Announce logout independently of the mutable SDK actor. Authentication or a
/// native keyring call can be in flight while the user signs out; the old
/// profile must already be durably revoked before that actor becomes available.
fn fenced_controls(
    mut incoming: mpsc::UnboundedReceiver<Request>,
    store: RuntimeStore,
    replies: mpsc::Sender<Reply>,
) -> mpsc::UnboundedReceiver<Request> {
    let (forward, receiver) = mpsc::unbounded_channel();
    tokio::spawn(async move {
        while let Some(request) = incoming.recv().await {
            if matches!(&request.work, Work::Command(UiCommand::Logout))
                && let Err(error) = store.revoke().await
            {
                let _ = replies
                    .send(Reply {
                        epoch: request.epoch,
                        view: View::Failed(error),
                    })
                    .await;
            }
            if forward.send(request).is_err() {
                break;
            }
        }
    });
    receiver
}
async fn finish_or_cancel<T>(
    operation: impl std::future::Future<Output = Result<T>>,
    cancel: &CancellationToken,
    grace: Duration,
) -> Result<T> {
    tokio::pin!(operation);
    tokio::select! {
        biased;
        result=&mut operation=>result,
        _=cancel.cancelled()=>tokio::time::timeout(grace,&mut operation).await.unwrap_or(Err(Error::Cancelled)),
    }
}
impl Actor {
    fn retire_cached_views(&self) {
        if let Some(previous) = self.cached_views.send_replace(None) {
            previous.views.close();
        }
    }
    fn stage_cached_views(&self, epoch: Stamp) {
        if self.cached_views_blocked || self.live_cancel.is_cancelled() {
            self.retire_cached_views();
            return;
        }
        // A disconnected socket does not revoke owned cache data. The SDK
        // requires the actual previously authenticated principal/owner epoch,
        // and retains any known monitor denial when a witness exists.
        let monitor = self.live_monitor.as_ref();
        let generation = self.store.generation_guard();
        let staged = self.client.stage_cached_chat_views(monitor, CancellationToken::new());
        let next = match staged {
            Ok(views) if generation.is_current() => Some(NativeCachedChatViews {
                views: std::sync::Arc::new(views), store_generation: generation, security: epoch.security,
            }),
            // Optional cached presentation never substitutes for failed auth or
            // durability. The original canonical path still reports its result.
            _ => None,
        };
        if let Some(previous) = self.cached_views.send_replace(next) {
            previous.views.close();
        }
    }
    async fn verify_trusted(&mut self, login: bool) -> Result<()> {
        let Some(path) = &self.trusted_path else {
            return Ok(());
        };
        self.trusted_verified = false;
        self.client.validate_session().await?;
        use openmates::cli::trusted_account as trusted;
        if login {
            trusted::save(path, self.client.user()["id"].as_str().unwrap_or(""))
                .map_err(|_| Error::Forbidden)?;
        } else {
            let expected = trusted::load(path).map_err(|_| Error::Forbidden)?;
            trusted::verify(expected.as_deref(), self.client.user())
                .map_err(|_| Error::Forbidden)?;
        }
        self.trusted_verified = true;
        Ok(())
    }
    async fn emit(replies: &mpsc::Sender<Reply>, epoch: Stamp, view: View) -> Result<()> {
        replies
            .send(Reply { epoch, view })
            .await
            .map_err(|_| Error::Cancelled)
    }
    async fn persist(&mut self) -> Result<()> {
        openmates::session_runtime::persist(
            &mut self.client,
            &self.store,
            self.passphrase.clone(),
        )
        .await
    }
    async fn authorized(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        self.authorized_with_inventory(replies, epoch, false).await.map(|_| ())
    }
    async fn authorized_with_inventory(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp,
        inventory: bool) -> Result<Option<FreshChatInventory>> {
        self.authorized_admission(replies, epoch).await?;
        self.recover_before_view_with_inventory(replies, epoch, None, false, inventory)
            .await.map(|outcome| outcome.fresh_inventory)
    }
    async fn authorized_admission(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        // This can start monitors and foreground recovery. Remove any restored
        // receipt durably before those effects, including a crash before a
        // recovery checkpoint/final save. Failure refuses their dispatch.
        openmates::session_runtime::revoke_chat_cache_before_dispatch(
            &mut self.client,
            &self.store,
            self.passphrase.clone(),
            &self.live_cancel,
        )
        .await?;
        let generation = self.store.generation_guard();
        let request = self.live_cancel.clone();
        // Reuse the already-required first monitor's authenticated session read
        // and exact persistence BEFORE the initial greeting. No extra request.
        let admission = self.monitor_admission(replies, epoch).await?;
        if let MonitorAdmission::Denied(error) = admission { return Err(error); }
        let storage = match self.store.storage_mode().await? {
            Some(openmates::storage::StorageMode::OsKeyring) => {
                "Signed in · credentials protected by OS keyring"
            }
            Some(openmates::storage::StorageMode::RestrictedLocalFile) => {
                "Signed in · credentials protected by owner-only local files"
            }
            Some(openmates::storage::StorageMode::EncryptedVault) => {
                "Signed in · credentials protected by passphrase vault"
            }
            None => "Signed in · credentials not stored",
        };
        // A newly admitted monitor has already staged this exact owner once.
        // Reuse it instead of decoding another cache projection.
        let staged = self.cached_views.borrow().clone();
        if staged.as_ref().is_none_or(|current| current.security != epoch.security
            || !current.store_generation.is_current() || !current.views.is_owner_current()) {
            self.stage_cached_views(epoch);
        }
        let owner = self.cached_views.borrow().clone().ok_or(Error::Offline)?;
        if !generation.is_current() || request.is_cancelled() || !owner.views.is_owner_current() {
            return Err(Error::Cancelled);
        }
        let session = self.client.session().ok_or(Error::Authentication)?;
        // The SDK stage above requires the principal established by actual
        // authentication. A raw restored Session cannot issue this greeting.
        let username = ["username", "display_name"].into_iter()
            .filter_map(|key| self.client.user()[key].as_str())
            .find(|name| !name.is_empty()).unwrap_or("OpenMates").to_owned();
        let publication = NativeAuthPublication { owner, request, username,
            expires_at: session.paired_session_expires_at };
        Self::emit(replies, epoch, View::AdmittedAuth(publication)).await?;
        let status = if matches!(admission, MonitorAdmission::Offline) {
            "Offline · reconnecting…"
        } else { storage };
        Self::emit(replies, epoch, View::Status(status)).await
    }
    async fn monitor(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        self.monitor_admission(replies, epoch).await.map(|_| ())
    }
    async fn monitor_admission(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<MonitorAdmission> {
        self.client.set_operation_cancel(self.live_cancel.clone());
        // Periodic membership checks do not reconnect a healthy monitor or
        // manufacture another initial full-refresh event every 30 seconds.
        if let Some(monitor) = self.live_monitor.as_ref().filter(|m| m.is_valid()) {
            let checked = self.client.validate_chat_monitor(monitor).await;
            let security = matches!(checked, Err(Error::Expired | Error::Authentication | Error::Forbidden));
            let admission = match checked {
                Ok(()) => MonitorAdmission::Ready,
                Err(error) if security => MonitorAdmission::Denied(error),
                Err(_) => MonitorAdmission::Offline,
            };
            if security {
                let error = checked.err().ok_or(Error::Protocol)?;
                let lifetime = self.live_lifetime.clone().unwrap_or_default();
                Self::emit(replies, epoch, View::Monitor(error, lifetime)).await?;
            }
            // Storage failure is reported independently and cannot suppress a
            // known security clear that was already enqueued above.
            self.persist().await?;
            if !security && let Err(error) = checked {
                let lifetime = self.live_lifetime.clone().unwrap_or_default();
                Self::emit(replies, epoch, View::Monitor(error, lifetime)).await?;
            }
            return Ok(admission);
        }
        self.live_monitor.take();
        self.live_pending.take();
        self.last_live_hint.take();
        if let Some(previous) = self.live_lifetime.take() {
            previous.cancel();
        }
        let lifetime = CancellationToken::new();
        self.live_lifetime = Some(lifetime.clone());
        self.live_epoch = epoch;
        let (events, mut errors) = mpsc::channel(8);
        let output = replies.clone();
        let error_lifetime = lifetime.clone();
        tokio::spawn(async move {
            while let Some(error) = errors.recv().await {
                if output
                    .send(Reply {
                        epoch,
                        view: View::Monitor(error, error_lifetime.clone()),
                    })
                    .await
                    .is_err()
                {
                    break;
                }
            }
        });
        let started = async {
            let mut grant = ForegroundRecoveryGrant::new(&mut self.client)?;
            grant.start_chat_monitor(lifetime.clone(), events).await
        }
        .await;
        let security = matches!(&started, Err(Error::Expired | Error::Authentication | Error::Forbidden));
        if security {
            let error = started.as_ref().err().copied().ok_or(Error::Protocol)?;
            Self::emit(replies, epoch, View::Monitor(error, lifetime.clone())).await?;
        }
        // Cookie rotation and local revocation are still attempted. Any failure
        // propagates as a separate storage error after the security notification.
        self.persist().await?;
        match started {
            Ok(monitor) => {
                self.live_monitor = Some(monitor);
                self.cached_views_blocked = false;
                // The monitor admission's exact credential/cache persist has
                // completed. Publish immutable cached data BEFORE recovery or
                // the initial canonical list can occupy the actor.
                self.stage_cached_views(epoch);
                self.live_retry_at = None;
                self.recovery_start_needed = true;
                self.recovery_blocked = false;
                self.recovery_retry_at = None;
                self.last_live_hint = None;
                Ok(MonitorAdmission::Ready)
            }
            Err(error) if security => Ok(MonitorAdmission::Denied(error)),
            Err(error) => {
                Self::emit(replies, epoch, View::Monitor(error, lifetime)).await?;
                Ok(MonitorAdmission::Offline)
            },
        }
    }
    fn recovery_due(&self) -> bool {
        if self.recovery_blocked {
            return false;
        }
        if self.recovery_start_needed {
            return true;
        }
        if let Some(deadline) = self.recovery_retry_at {
            return tokio::time::Instant::now() >= deadline;
        }
        !self.recovery_hints.is_empty()
    }
    async fn recover_before_view(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
        selected: Option<String>,
        force: bool,
    ) -> Result<bool> {
        self.recover_before_view_with_inventory(replies, epoch, selected, force, false)
            .await.map(|outcome| outcome.canonical_changed)
    }
    async fn recover_before_view_with_inventory(
        &mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp, selected: Option<String>,
        force: bool, inventory: bool,
    ) -> Result<CompletionRecoveryPumpOutcome> {
        if !force && !self.recovery_due() {
            return Ok(CompletionRecoveryPumpOutcome::default());
        }
        if self.live_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if !self
            .live_monitor
            .as_ref()
            .is_some_and(|monitor| monitor.is_valid())
        {
            return Ok(CompletionRecoveryPumpOutcome::default());
        }
        // Existing Team/Direct recovery keeps its original ordinary policy.
        let inventory = inventory && self.client.supports_cached_default_chat_list();
        let cancel = self.live_cancel.clone();
        self.client.set_operation_cancel(cancel.clone());
        let mut canonical = RecoveryPersistence::new(self)?;
        let store = self.store.clone();
        let pumped = async {
            let mut grant = ForegroundRecoveryGrant::new(&mut self.client)?;
            let total: CompletionRecoveryPumpOutcome;
            // Selected work gets the first two slots; the remaining six still
            // service bounded context backlog, so staying on one chat cannot
            // starve every other recoverable chat indefinitely.
            if let Some(id) = selected {
                // Opening a chat discovers only that chat's recovery work on
                // its authenticated socket (like `chats show`), never a global
                // full sync; boot, refresh and live hints keep global recovery.
                total = completion_recovery_adapter::pump_completion_recovery_for_saved_read(
                    &mut grant,
                    &store,
                    CompletionRecoveryPumpOptions {
                        selected_chat: Some(id),
                        max_attempts: 2,
                    },
                    &cancel,
                    &mut canonical,
                    false,
                )
                .await?;
            } else {
                total = completion_recovery_adapter::pump_completion_recovery_with_inventory(
                    &mut grant,
                    &store,
                    CompletionRecoveryPumpOptions {
                        selected_chat: None,
                        max_attempts: 8,
                    },
                    &cancel,
                    &mut canonical,
                    inventory,
                )
                .await?;
            }
            Ok::<_, Error>(total)
        }
        .await;
        match pumped {
            Ok(outcome) => {
                if cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                self.recovery_start_needed = false;
                self.recovery_blocked = false;
                self.recovery_hints.clear();
                self.recovery_retry_at = (outcome.deferred > 0 || outcome.attempted >= 8)
                    .then(|| tokio::time::Instant::now() + Duration::from_secs(5));
                if outcome.canonical_changed && self.live_pending.is_none() {
                    // Reuse only an opaque same-instance invalidation, never a
                    // pre-pump ChatRefresh/model/checkpoint.
                    self.live_pending = self.last_live_hint.take();
                }
                self.persist().await?;
                if outcome.deferred > 0 {
                    Self::emit(
                        replies,
                        epoch,
                        View::Status("Response recovery pending · retrying shortly"),
                    )
                    .await?;
                }
                Ok(outcome)
            }
            Err(error @ (Error::Expired | Error::Forbidden)) => {
                let mut security = (error == Error::Expired).then_some(Error::Expired);
                // Generic job/Direct Forbidden is not an account revocation.
                // Fresh current session/Team admission confirms any scope clear.
                if error == Error::Forbidden
                    && let Some(monitor) = self.live_monitor.as_ref()
                {
                    match self.client.validate_chat_monitor(monitor).await {
                        Err(denial @ (Error::Expired | Error::Forbidden)) => {
                            security = Some(denial)
                        }
                        Ok(()) => {}
                        Err(other) => return Err(other),
                    }
                }
                if security.is_none() {
                    self.recovery_start_needed = false;
                    self.recovery_retry_at =
                        Some(tokio::time::Instant::now() + Duration::from_secs(5));
                }
                if let Some(denial) = security {
                    let lifetime = self.live_lifetime.clone().unwrap_or_default();
                    Self::emit(replies, epoch, View::Monitor(denial, lifetime)).await?;
                }
                // Security notification is already enqueued even if this fails.
                self.persist().await?;
                Err(error)
            }
            Err(error @ (Error::Offline | Error::Protocol | Error::Io | Error::Conflict)) => {
                self.recovery_start_needed = false;
                self.recovery_retry_at = Some(tokio::time::Instant::now() + Duration::from_secs(5));
                self.persist().await?;
                Self::emit(
                    replies,
                    epoch,
                    View::Status("Canonical completion recovery pending · will retry"),
                )
                .await?;
                let _ = error;
                Ok(CompletionRecoveryPumpOutcome::default())
            }
            Err(Error::Cancelled) => Err(Error::Cancelled),
            Err(error) => {
                // Corrupt/unsupported local state is not repaired by hammering
                // discovery on every tick. Preserve it and report; explicit
                // saved read/reconnect/context admission may probe again.
                self.recovery_start_needed = false;
                self.recovery_blocked = true;
                self.recovery_retry_at = None;
                Err(error)
            }
        }
    }
    async fn live_update(&mut self, replies: &mpsc::Sender<Reply>) -> Result<()> {
        if self.live_cancel.is_cancelled()
            || self.pair_phase != 0
            || self
                .live_retry_at
                .is_some_and(|at| at > tokio::time::Instant::now())
        {
            return Ok(());
        }
        if !self
            .live_monitor
            .as_ref()
            .is_some_and(|monitor| monitor.is_valid())
        {
            return Ok(());
        }
        if self.live_pending.is_none() {
            self.live_pending = self
                .live_monitor
                .as_ref()
                .ok_or(Error::Cancelled)?
                .take_pending()?;
        }
        let revisit = self.live_pending.is_none() && self.recovery_due();
        if revisit {
            self.live_pending = self.last_live_hint.take();
        }
        if let Some(hint) = self.live_pending.as_ref() {
            for id in hint.recovery_chats() {
                if self.recovery_hints.len() < 100 {
                    self.recovery_hints.insert(id.to_owned());
                }
            }
        }
        let selected = self.live_selected.clone();
        let canonical_changed = self
            .recover_before_view(replies, self.live_epoch, selected.clone(), false)
            .await?;
        if revisit && !canonical_changed {
            self.last_live_hint = self.live_pending.take();
            return Ok(());
        }
        let Some(monitor) = self
            .live_monitor
            .as_ref()
            .filter(|monitor| monitor.is_valid())
        else {
            return Ok(());
        };
        let Some(hint) = self.live_pending.as_ref() else {
            return Ok(());
        };
        self.client.set_operation_cancel(self.live_cancel.clone());
        let store_generation = self.store.generation_guard();
        let refreshed = self
            .client
            .refresh_chat_monitor_prefer_cache(monitor, hint, selected.as_deref())
            .await;
        match refreshed {
            Ok(refresh) => {
                // The actor remains sole Client owner across read, exact
                // cache+session save and ACK, explicit commit, and publication.
                self.client.validate_chat_refresh(&refresh)?;
                let receipt = ChatRefreshDurableReceipt {
                    ciphertext_sha256: refresh.ciphertext_sha256()?,
                    credential_revision: refresh.credential_revision(),
                };
                self.persist().await?;
                if !store_generation.is_current() { return Err(Error::Cancelled); }
                let publication = self.client.commit_chat_refresh(refresh, receipt)?;
                if self.live_cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                Self::emit(replies, self.live_epoch, View::Live(NativeLivePublication {
                    publication, store_generation, request: self.live_cancel.clone(),
                })).await?;
                self.stage_cached_views(self.live_epoch);
                self.last_live_hint = self.live_pending.take();
                Ok(())
            }
            Err(error @ (Error::Expired | Error::Forbidden))
                if self
                    .live_monitor
                    .as_ref()
                    .is_some_and(|monitor| !monitor.is_valid()) =>
            {
                self.live_pending.take();
                let denial = self
                    .live_monitor
                    .as_ref()
                    .ok_or(Error::Cancelled)?
                    .access_denial()?;
                if let Some(denial) = denial {
                    let lifetime = self.live_lifetime.clone().unwrap_or_default();
                    Self::emit(
                        replies,
                        self.live_epoch,
                        View::AccessDenied(denial, lifetime),
                    )
                    .await?;
                } else if error == Error::Expired {
                    let lifetime = self.live_lifetime.clone().unwrap_or_default();
                    Self::emit(replies, self.live_epoch, View::Monitor(error, lifetime)).await?;
                } else {
                    return Err(error);
                }
                self.persist().await
            }
            Err(Error::Cancelled)
                if self
                    .live_monitor
                    .as_ref()
                    .is_some_and(|monitor| monitor.is_valid()) =>
            {
                // An ordinary UI Cancel invalidates only this read token.
                // Keep the hint for the next admitted active token. Even a
                // forced outer-future drop leaves live_pending owned by Actor;
                // tick is disabled while live_cancel stays canceled.
                self.live_monitor
                    .as_ref()
                    .ok_or(Error::Cancelled)?
                    .requeue(self.live_pending.take().ok_or(Error::Cancelled)?)?;
                self.persist().await?;
                Ok(())
            }
            Err(error @ (Error::Offline | Error::Protocol | Error::Io)) => {
                // A failed read has no write retry. Preserve hint until a
                // bounded later canonical read; rotated cookies remain durable.
                self.live_monitor
                    .as_ref()
                    .ok_or(Error::Cancelled)?
                    .requeue(self.live_pending.take().ok_or(Error::Cancelled)?)?;
                self.live_retry_at = Some(tokio::time::Instant::now() + Duration::from_secs(2));
                self.persist().await?;
                Self::emit(
                    replies,
                    self.live_epoch,
                    View::Status("Live updates delayed · canonical refresh pending"),
                )
                .await?;
                let _ = error;
                Ok(())
            }
            Err(error) => {
                self.live_pending.take();
                Err(error)
            }
        }
    }
    async fn boot(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        let session = match self.store.load(self.passphrase.clone()).await {
            Ok(value) => value,
            Err(Error::Locked)
                if self.store.storage_mode().await?
                    == Some(openmates::storage::StorageMode::EncryptedVault) =>
            {
                Self::emit(replies, epoch, View::Unlock).await?;
                return Ok(());
            }
            Err(Error::Expired) => {
                self.store.clear().await?;
                None
            }
            Err(error) => return Err(error),
        };
        if let Some(session) = session {
            let api = self
                .explicit_api
                .as_deref()
                .unwrap_or(&session.api_url)
                .to_owned();
            let app = openmates::profile::application_origin(
                &api,
                self.explicit_app.clone(),
                self.installed_app.as_ref().map(|(api, _)| api.as_str()),
                self.installed_app.as_ref().map(|(_, app)| app.clone()),
            )?;
            self.client.set_app_origin(app)?;
            self.client.reset(&api, Some(session.clone()))?;
            self.trusted_verified = false;
            self.verify_trusted(false).await?;
            if let Some(snapshot) = self
                .store
                .read_cache(
                    session.hashed_email.clone(),
                    cache_key(&session),
                    session.master_key.clone(),
                )
                .await?
            {
                self.client.restore_ciphertext_snapshot(&snapshot)?;
                Self::emit(
                    replies,
                    epoch,
                    View::Items(Workspace::Chats, self.client.cached_chat_items()?),
                )
                .await?;
            }
            // Authenticate and admit the monitor now; global recovery and the
            // list refresh follow as a preemptible background BootSync.
            self.authorized_admission(replies, epoch).await?;
        } else {
            Self::emit(replies, epoch, View::SignedOut).await?;
        }
        Ok(())
    }
    /// Background half of boot: global recovery with inventory, then the list.
    async fn boot_sync(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        if self.client.session().is_none() {
            return Ok(());
        }
        let generation = self.store.generation_guard();
        let cancel = self.live_cancel.clone();
        // Reuse only the same-batch complete empty inventory returned after
        // actual recovery/journal admission and its existing durable save.
        // No phase1b/cache/history data is promoted to full selected reads.
        let proof = self
            .recover_before_view_with_inventory(replies, epoch, None, false, true)
            .await?
            .fresh_inventory;
        if cancel.is_cancelled() || !generation.is_current() { return Err(Error::Cancelled); }
        let items = if let Some(proof) = proof {
            self.client.list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel).await?
        } else {
            self.client.list(Workspace::Chats).await?
        };
        self.persist().await?;
        if cancel.is_cancelled() || !generation.is_current() { return Err(Error::Cancelled); }
        Self::emit(replies, epoch, View::Items(Workspace::Chats, items)).await
    }
    async fn pair_poll(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
        cancel: &CancellationToken,
    ) -> Result<()> {
        match self.pair_phase {
            1 => {
                if self.client.poll_pair().await? == "approved" {
                    self.pair_phase = 2;
                    Self::emit(replies, epoch, View::PairPin).await?;
                }
            }
            3 if self.client.finish_pair().await? => {
                self.pair_phase = 4;
                self.finish_pair(replies, epoch, cancel).await?;
            }
            _ => {}
        }
        Ok(())
    }
    async fn finish_pair(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
        cancel: &CancellationToken,
    ) -> Result<()> {
        if cancel.is_cancelled() {
            self.abort_pair().await?;
            return Err(Error::Cancelled);
        }
        if let Err(error) = self.verify_trusted(true).await {
            self.abort_pair().await?;
            return Err(error);
        }
        if cancel.is_cancelled() {
            self.abort_pair().await?;
            return Err(Error::Cancelled);
        }
        self.store
            .begin_session_cancellable(
                self.client.clone_session().ok_or(Error::Authentication)?,
                cancel.clone(),
            )
            .await?;
        let result = self.persist().await;
        if cancel.is_cancelled() {
            self.abort_pair().await?;
            return Err(Error::Cancelled);
        }
        if result == Err(Error::Locked) {
            Self::emit(replies, epoch, View::Unlock).await?;
            return Ok(());
        }
        result?;
        self.client.acknowledge_pair().await?;
        if cancel.is_cancelled() {
            self.store.clear().await?;
            let _ = self.client.logout().await;
            self.passphrase = None;
            self.pair_phase = 0;
            return Err(Error::Cancelled);
        }
        self.pair_phase = 0;
        self.authorized(replies, epoch).await?;
        let items = self.client.list(Workspace::Chats).await?;
        self.persist().await?;
        Self::emit(replies, epoch, View::Items(Workspace::Chats, items)).await
    }
    async fn abort_pair(&mut self) -> Result<()> {
        let prepared = self.pair_phase == 4;
        self.pair_phase = 0;
        let cleanup = if prepared {
            self.passphrase = None;
            self.store.clear().await
        } else {
            Ok(())
        };
        let cancelled = self.client.cancel_pair().await;
        // Also cover cancellation immediately after relay acknowledgement removed
        // its PairState, before the UI accepted the newly persisted session.
        if prepared {
            let _ = self.client.logout().await;
        }
        cleanup?;
        cancelled
    }
    async fn dispatch(&mut self, request: Request, replies: &mpsc::Sender<Reply>) -> Result<()> {
        if matches!(&request.work, Work::Command(
            UiCommand::Logout | UiCommand::SwitchTeam(_) | UiCommand::Login { .. }
            | UiCommand::BeginPair | UiCommand::PairPin { .. } | UiCommand::Unlock { .. }
        )) {
            self.retire_cached_views();
        }
        let logout = matches!(&request.work, Work::Command(UiCommand::Logout));
        if !matches!(&request.work, Work::Live) {
            self.live_cancel = request.cancel.clone();
        }
        if matches!(
            &request.work,
            Work::Command(UiCommand::Logout | UiCommand::SwitchTeam(_))
        ) {
            self.live_monitor.take();
            self.live_pending.take();
            if let Some(lifetime) = self.live_lifetime.take() {
                lifetime.cancel();
            }
            self.live_selected = None;
            self.recovery_hints.clear();
            self.recovery_start_needed = true;
            self.recovery_blocked = false;
            self.recovery_retry_at = None;
            self.last_live_hint = None;
        }
        if request.cancel.is_cancelled() && !logout {
            return Err(Error::Cancelled);
        }
        if self.trusted_path.is_some()
            && !self.trusted_verified
            && !matches!(
                &request.work,
                Work::Boot
                    | Work::PairPoll
                    | Work::Command(
                        UiCommand::Login { .. }
                            | UiCommand::BeginPair
                            | UiCommand::PairPin { .. }
                            | UiCommand::Unlock { .. }
                            | UiCommand::Logout
                            | UiCommand::Cancel
                    )
            )
        {
            return Err(Error::Forbidden);
        }
        let cancel = request.cancel.clone();
        // Logout is irreversible local cleanup, even when its old UI token was
        // cancelled by a newer command. Auth admission has explicit rollback.
        let admission = logout
            || matches!(
                &request.work,
                Work::PairPoll
                    | Work::Command(
                        UiCommand::Login { .. } | UiCommand::BeginPair | UiCommand::PairPin { .. }
                    )
            )
            || self.pair_phase > 0
                && matches!(&request.work, Work::Command(UiCommand::Unlock { .. }));
        // process owns the selected command's boxed future; retain that exact
        // operation through the existing admission/cancellation boundary.
        // A preempted background sync yields at once; its effects are fenced
        // like any other dropped operation and it reruns from the start.
        let grace = if matches!(&request.work, Work::BootSync) { Duration::ZERO } else { Duration::from_secs(2) };
        let operation = self.process(request, replies);
        if admission {
            operation.await
        } else {
            finish_or_cancel(operation, &cancel, grace).await
        }
    }
    // Select one operation before polling. Each action has its own coroutine
    // instead of sharing one monolithic match poll frame across every action.
    // Selection only moves owned inputs: all IO/policy checks remain inside the
    // selected async body and the caller retains the original cancellation gate.
    fn process<'a>(
        &'a mut self,
        request: Request,
        replies: &'a mpsc::Sender<Reply>,
    ) -> futures_util::future::BoxFuture<'a, Result<()>> {
        let epoch = request.epoch;
        let cancel = request.cancel;
        match request.work {
            Work::Boot => Box::pin(async move {
                let _request_cancel = &cancel;
                self.boot(replies, epoch).await
            }),
            Work::BootSync => Box::pin(async move {
                let _request_cancel = &cancel;
                self.boot_sync(replies, epoch).await
            }),
            Work::PairPoll => Box::pin(async move {
                let _request_cancel = &cancel;
                self.pair_poll(replies, epoch, &cancel).await
            }),
            Work::Monitor => Box::pin(async move {
                let _request_cancel = &cancel;
                self.monitor(replies, epoch).await?;
                self.recover_before_view(replies, epoch, None, false)
                    .await
                    .map(|_| ())
            }),
            Work::Live => Box::pin(async move {
                let _request_cancel = &cancel;
                self.live_update(replies).await
            }),
            Work::Command(command) => match command {
                UiCommand::Login {
                    email,
                    password,
                    tfa,
                } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    if self.client.session().is_some() {
                        return Err(Error::Invalid(
                            "Sign out before signing in to another account.",
                        ));
                    }
                    self.client
                        .login_password(&email, &password, tfa.as_deref())
                        .await?;
                    if let Err(error) = self.verify_trusted(true).await {
                        let _ = self.client.logout().await;
                        self.trusted_verified = false;
                        return Err(error);
                    }
                    if cancel.is_cancelled() {
                        let _ = self.client.logout().await;
                        return Err(Error::Cancelled);
                    }
                    if let Err(error) = self
                        .store
                        .begin_session_cancellable(
                            self.client.clone_session().ok_or(Error::Authentication)?,
                            cancel.clone(),
                        )
                        .await
                    {
                        let _ = self.client.logout().await;
                        return Err(error);
                    }
                    self.passphrase = Some(password);
                    if let Err(error) = self.persist().await {
                        let _ = self.client.logout().await;
                        self.passphrase = None;
                        return Err(error);
                    }
                    if cancel.is_cancelled() {
                        let cleanup = self.store.clear().await;
                        let _ = self.client.logout().await;
                        self.passphrase = None;
                        cleanup?;
                        return Err(Error::Cancelled);
                    }
                    self.authorized(replies, epoch).await?;
                    let items = self.client.list(Workspace::Chats).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(Workspace::Chats, items)).await
                }),
                UiCommand::Unlock { passphrase } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.passphrase = Some(passphrase);
                    let result = if self.pair_phase == 4 {
                        self.finish_pair(replies, epoch, &cancel).await
                    } else {
                        self.boot(replies, epoch).await
                    };
                    if result.is_err() {
                        self.passphrase = None
                    }
                    result
                }),
                UiCommand::Logout => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.trusted_verified = false;
                    self.pair_phase = 0;
                    self.passphrase = None;
                    let (remote, local) = tokio::join!(self.client.logout(), self.store.clear());
                    Self::emit(replies, epoch, View::SignedOut).await?;
                    local?;
                    remote
                }),
                UiCommand::Cancel => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.abort_pair().await?;
                    if self.client.session().is_some() {
                        self.authorized(replies, epoch).await?;
                        if let Ok(items) = self.client.cached_chat_items() {
                            Self::emit(replies, epoch, View::Items(Workspace::Chats, items))
                                .await?;
                        }
                    } else {
                        Self::emit(replies, epoch, View::SignedOut).await?;
                    }
                    Ok(())
                }),
                UiCommand::BeginPair => Box::pin(async move {
                    let _request_cancel = &cancel;
                    if self.client.session().is_some() {
                        return Err(Error::Invalid("Sign out before pairing another account."));
                    }
                    let challenge = self.client.begin_pair().await?;
                    self.pair_phase = 1;
                    if cancel.is_cancelled() {
                        self.abort_pair().await?;
                        return Err(Error::Cancelled);
                    }
                    Self::emit(replies, epoch, View::PairUri(challenge.login_url)).await
                }),
                UiCommand::PairPin {
                    pin,
                    vault_passphrase,
                } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.client.submit_pair_pin(&pin).await?;
                    self.passphrase = vault_passphrase;
                    self.pair_phase = 3;
                    Self::emit(
                        replies,
                        epoch,
                        View::Status("Waiting for the browser to finish pairing…"),
                    )
                    .await
                }),
                UiCommand::SwitchTeam(team) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.client.set_team(team.as_deref())?;
                    self.persist().await?;
                    self.authorized(replies, epoch).await?;
                    let items = self.client.list(Workspace::Chats).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(Workspace::Chats, items)).await
                }),
                UiCommand::Refresh(workspace) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    if workspace == Workspace::Chats {
                        self.recover_before_view(replies, epoch, self.live_selected.clone(), true)
                            .await?;
                    }
                    let items = self.client.list(workspace).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(workspace, items)).await
                }),
                UiCommand::Open(workspace, id) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    let generation = self.store.generation_guard();
                    let view = if workspace == Workspace::Chats {
                        uuid::Uuid::parse_str(&id)
                            .map_err(|_| Error::Invalid("A full chat ID is required."))?;
                        if self.client.is_ephemeral_chat(&id) {
                            return Err(Error::Invalid(
                                "Volatile chats have no saved recovery history.",
                            ));
                        }
                        self.recover_before_view(replies, epoch, Some(id.clone()), true)
                            .await?;
                        let mut first_page = NativeChatFirstPageSink {
                            store: self.store.clone(), generation: generation.clone(),
                            passphrase: self.passphrase.clone(), replies: replies.clone(), epoch,
                        };
                        let read = self.client.read_chat_view_prefer_cache_with_first_page(
                            self.live_monitor.as_ref(), &id, cancel.clone(), &mut first_page,
                        ).await?;
                        if !generation.is_current() { return Err(Error::Cancelled); }
                        self.live_selected = Some(id.clone());
                        match read {
                            ChatViewRead::Canonical(candidate) => {
                                self.client.validate_chat_view(&candidate)?;
                                let receipt = ChatRefreshDurableReceipt {
                                    ciphertext_sha256: candidate.ciphertext_sha256()?,
                                    credential_revision: candidate.credential_revision(),
                                };
                                self.persist().await?;
                                if !generation.is_current() { return Err(Error::Cancelled); }
                                let publication = self.client.commit_chat_view(candidate, receipt)?;
                                return Self::emit(replies, epoch, View::CanonicalChat(NativeCanonicalChatPublication {
                                    publication, store_generation: generation,
                                })).await;
                            },
                            ChatViewRead::CacheSettled(candidate) => {
                                self.client.validate_cache_settlement(&candidate)?;
                                let receipt = ChatRefreshDurableReceipt {
                                    ciphertext_sha256: candidate.ciphertext_sha256()?,
                                    credential_revision: candidate.credential_revision(),
                                };
                                self.persist().await?;
                                if !generation.is_current() { return Err(Error::Cancelled); }
                                let publication = self.client.commit_cache_settlement(candidate, receipt)?;
                                return Self::emit(replies, epoch, View::CacheSettled(NativeCacheSettlementPublication {
                                    publication, store_generation: generation,
                                })).await;
                            },
                            ChatViewRead::CachedOffline(publication) => {
                                if self.cached_views_blocked { return Err(Error::Forbidden); }
                                View::CachedChatOffline(NativeCachedChatPublication {
                                    publication, store_generation: generation.clone(),
                                })
                            },
                        }
                    } else {
                        View::Item(workspace, self.client.detail(workspace, &id).await?)
                    };
                    self.persist().await?;
                    if !generation.is_current() { return Err(Error::Cancelled); }
                    Self::emit(replies, epoch, view).await
                }),
                UiCommand::Mutate(mutation) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.client.set_operation_cancel(cancel.clone());
                    let workspace = match &mutation {
                        Mutation::Create { workspace, .. }
                        | Mutation::Update { workspace, .. }
                        | Mutation::Delete { workspace, .. } => *workspace,
                        Mutation::RunWorkflow { .. } => Workspace::Workflows,
                        Mutation::SetSetting { .. } => Workspace::Settings,
                    };
                    let item = self.client.mutate(mutation).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::MutationSucceeded).await?;
                    if workspace == Workspace::Apps
                        && let Some(item) = item
                    {
                        Self::emit(replies, epoch, View::Item(workspace, item)).await?;
                    }
                    let items = self.client.list(workspace).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(workspace, items)).await
                }),
                UiCommand::Send { chat_id, text } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    // Same send-time mention resolution as `chats send`; an
                    // unknown mention fails before dispatch and restores the draft.
                    let resolved = self.client.resolve_mentions(&text).await?;
                    if !resolved.unresolved.is_empty() {
                        return Err(Error::Invalid(
                            "Unknown @mention. Nothing was sent; check the mention name.",
                        ));
                    }
                    let text = resolved.processed_message;
                    let (stream, mut updates) = mpsc::channel(64);
                    let output = replies.clone();
                    self.relay = Some(tokio::spawn(async move {
                        while let Some(update) = updates.recv().await {
                            if output
                                .send(Reply {
                                    epoch,
                                    view: View::Stream(update),
                                })
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }));
                    let result = self
                        .client
                        .send_message(chat_id.as_deref(), &text, stream, cancel.clone())
                        .await;
                    if let Some(relay) = self.relay.as_mut() {
                        let _ = relay.await;
                    }
                    self.relay = None;
                    // Preserve rotated cookies and any admitted encrypted state, including cancellation.
                    let persisted = self.persist().await;
                    if cancel.is_cancelled() {
                        return Err(Error::Cancelled);
                    }
                    persisted?;
                    let chat = result?;
                    self.live_selected = Some(chat.id.clone());
                    Self::emit(replies, epoch, View::Sent(chat)).await
                }),
                UiCommand::Share {
                    chat_id,
                    expires_in,
                    password,
                    include_sensitive,
                } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    let uri = self
                        .client
                        .share_chat(&chat_id, expires_in, &password, include_sensitive)
                        .await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Share(uri)).await
                }),
                UiCommand::Download {
                    workspace,
                    id,
                    destination,
                    overwrite,
                } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.client
                        .download(workspace, &id, &destination, overwrite)
                        .await?;
                    self.persist().await?;
                    Self::emit(
                        replies,
                        epoch,
                        View::Status("Saved to the requested local path"),
                    )
                    .await
                }),
                other => Box::pin(async move {
                    let _request_cancel = &cancel;
                    drop(other);
                    Err(Error::Invalid("This action is handled by the terminal."))
                }),
            },
        }
    }
}
fn cache_key(session: &Session) -> String {
    openmates::session_runtime::cache_key(session)
}
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture_session() -> Session {
        Session {
            api_url: "https://api.example.com".into(),
            session_id: uuid::Uuid::new_v4().to_string(),
            cookies: Default::default(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: now_ms(),
            paired_session_expires_at: None,
            active_team_id: None,
        }
    }
    pub(super) async fn fixture() -> (tempfile::TempDir, Actor) {
        #[cfg(unix)]
        use std::os::unix::fs::DirBuilderExt;
        let directory = tempfile::tempdir().unwrap();
        let profile = directory.path().join("profile");
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        builder.mode(0o700);
        builder.create(&profile).unwrap();
        let store = RuntimeStore::new(Some(profile), true).await.unwrap();
        let session = fixture_session();
        let actor = Actor {
            client: Client::new(&session.api_url, Some(session.clone())).unwrap(),
            store,
            passphrase: Some(Zeroizing::new("fixture passphrase".into())),
            pair_phase: 0,
            relay: None,
            explicit_api: None,
            explicit_app: None,
            installed_app: None,
            trusted_path: None,
            trusted_verified: false,
            live_monitor: None,
            live_pending: None,
            live_lifetime: None,
            live_epoch: Stamp::default(),
            live_cancel: CancellationToken::new(),
            live_retry_at: None,
            live_selected: None,
            recovery_hints: Default::default(),
            recovery_start_needed: true,
            recovery_blocked: false,
            recovery_retry_at: None,
            last_live_hint: None,
            cached_views: watch::channel(None).0,
            cached_views_blocked: false,
        };
        (directory, actor)
    }
    #[test]
    fn delayed_views_cannot_reopen_previous_navigation_or_owner() {
        let current = Stamp {
            security: 4,
            view: 12,
        };
        assert!(!current.accepts(&Reply {
            epoch: Stamp {
                security: 3,
                view: 12
            },
            view: View::Chat(Chat::default())
        }));
        assert!(!current.accepts(&Reply {
            epoch: Stamp {
                security: 4,
                view: 11
            },
            view: View::Chat(Chat::default())
        }));
        assert!(!current.accepts(&Reply {
            epoch: Stamp {
                security: 3,
                view: 12
            },
            view: View::Auth {
                username: "other owner".into(),
                expires_at: None
            }
        }));
        assert!(current.accepts(&Reply {
            epoch: current,
            view: View::Chat(Chat::default())
        }));
        // A late owned list may populate its cache, but cannot navigate the UI.
        assert!(current.accepts(&Reply {
            epoch: Stamp {
                security: 4,
                view: 11
            },
            view: View::Items(Workspace::Tasks, vec![])
        }));
    }
    #[tokio::test]
    async fn unverified_trusted_account_cannot_read_workspace_from_an_existing_session() {
        let (directory, mut actor) = fixture().await;
        actor.trusted_path = Some(directory.path().join("profile"));
        actor.trusted_verified = false;
        let (replies, mut views) = mpsc::channel(8);
        let result = actor
            .dispatch(
                Request {
                    epoch: Stamp::default(),
                    work: Work::Command(UiCommand::Refresh(Workspace::Chats)),
                    cancel: CancellationToken::new(),
                },
                &replies,
            )
            .await;
        assert_eq!(result, Err(Error::Forbidden));
        assert!(views.try_recv().is_err());
    }
    #[tokio::test]
    async fn cancelled_prepared_pair_removes_durable_session_even_after_relay_state_disappeared() {
        let (_directory, mut actor) = fixture().await;
        actor.persist().await.unwrap();
        assert!(
            actor
                .store
                .load(actor.passphrase.clone())
                .await
                .unwrap()
                .is_some()
        );
        actor.pair_phase = 4;
        let cancel = CancellationToken::new();
        cancel.cancel();
        let (replies, _) = mpsc::channel(8);
        assert_eq!(
            actor.finish_pair(&replies, Stamp::default(), &cancel).await,
            Err(Error::Cancelled)
        );
        assert!(actor.client.session().is_none());
        assert!(actor.passphrase.is_none());
        assert!(actor.store.load(None).await.unwrap().is_none());
    }
    #[tokio::test]
    async fn another_login_cannot_replace_an_active_owner() {
        let (_directory, mut actor) = fixture().await;
        let original = actor.client.session().unwrap().session_id.clone();
        let (replies, _) = mpsc::channel(8);
        let request = Request {
            epoch: Stamp::default(),
            cancel: CancellationToken::new(),
            work: Work::Command(UiCommand::Login {
                email: "someone@example.com".into(),
                password: Zeroizing::new("secret".into()),
                tfa: None,
            }),
        };
        assert_eq!(
            actor.process(request, &replies).await,
            Err(Error::Invalid(
                "Sign out before signing in to another account."
            ))
        );
        assert_eq!(actor.client.session().unwrap().session_id, original);
    }
    #[tokio::test]
    async fn priority_logout_is_admitted_when_ordinary_queue_is_full() {
        let (normal, mut pending) = mpsc::channel(1);
        let (critical, mut security) = mpsc::unbounded_channel();
        normal
            .try_send(Request {
                epoch: Stamp::default(),
                work: Work::Boot,
                cancel: CancellationToken::new(),
            })
            .unwrap_or_else(|_| panic!("empty queue"));
        assert!(
            normal
                .try_send(Request {
                    epoch: Stamp::default(),
                    work: Work::Boot,
                    cancel: CancellationToken::new()
                })
                .is_err()
        );
        critical
            .send(Request {
                epoch: Stamp::default(),
                work: Work::Command(UiCommand::Logout),
                cancel: CancellationToken::new(),
            })
            .unwrap_or_else(|_| panic!("security lane closed"));
        let admitted=tokio::select!{biased; request=security.recv()=>request,request=pending.recv()=>request}.unwrap();
        assert!(matches!(admitted.work, Work::Command(UiCommand::Logout)));
    }
    #[tokio::test]
    async fn queued_logout_revokes_profile_before_sdk_actor_reads_the_request() {
        let (_directory, mut actor) = fixture().await;
        actor.persist().await.unwrap();
        let (critical, incoming) = mpsc::unbounded_channel();
        let (replies, _views) = mpsc::channel(8);
        let mut pending = fenced_controls(incoming, actor.store.clone(), replies);
        critical
            .send(Request {
                epoch: Stamp::default(),
                work: Work::Command(UiCommand::Logout),
                cancel: CancellationToken::new(),
            })
            .unwrap_or_else(|_| panic!("security lane closed"));
        // Receiving here does not dispatch through the SDK actor. The independent
        // lane has already completed durable revocation before forwarding.
        let request = tokio::time::timeout(Duration::from_secs(2), pending.recv())
            .await
            .unwrap()
            .unwrap();
        assert!(matches!(request.work, Work::Command(UiCommand::Logout)));
        assert!(
            actor
                .store
                .load(actor.passphrase.clone())
                .await
                .unwrap()
                .is_none()
        );
        assert_eq!(actor.persist().await, Err(Error::Locked));
        assert!(actor.client.session().is_some());
    }
    #[tokio::test]
    async fn stalled_protocol_work_releases_actor_for_logout_after_cancellation() {
        let cancel = CancellationToken::new();
        let trigger = cancel.clone();
        let operation = async {
            trigger.cancel();
            std::future::pending::<Result<()>>().await
        };
        let result = tokio::time::timeout(
            Duration::from_secs(1),
            finish_or_cancel(operation, &cancel, Duration::from_millis(20)),
        )
        .await;
        assert_eq!(result, Ok(Err(Error::Cancelled)));
    }
    #[tokio::test]
    async fn cancelled_token_cannot_suppress_queued_logout() {
        let (_directory, mut actor) = fixture().await;
        actor.persist().await.unwrap();
        let cancel = CancellationToken::new();
        cancel.cancel();
        let (replies, _) = mpsc::channel(8);
        let result = actor
            .dispatch(
                Request {
                    epoch: Stamp::default(),
                    cancel,
                    work: Work::Command(UiCommand::Logout),
                },
                &replies,
            )
            .await;
        // The observer was dropped; cleanup still precedes notification.
        assert_eq!(result, Err(Error::Cancelled));
        assert!(actor.client.session().is_none());
        assert!(actor.passphrase.is_none());
        assert!(actor.store.load(None).await.unwrap().is_none());
    }
}

#[cfg(test)]
#[path = "runtime_live_tests.rs"]
mod live_tests;

#[cfg(test)]
#[path="runtime_late_cached_tests.rs"]
mod late_cached_tests;
