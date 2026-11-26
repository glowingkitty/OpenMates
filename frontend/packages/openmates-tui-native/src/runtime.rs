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
        CachedChatFilePublication, CachedChatFileReader, CachedChatWindow,
        ChatInvalidation, ChatMonitorAccessDenial, ChatSelectionUpdate,
        Client, FreshChatInventory,
    },
    completion_recovery_adapter::{
        self, CanonicalRecoveryPersistence, CompletionRecoveryPumpOptions,
        CompletionRecoveryPumpOutcome,
    },
    error::{Error, Result},
    model::{Chat, Item, Message, Mutation, StreamUpdate, Workspace},
    runtime_store::{RuntimeStore, RuntimeStoreGeneration},
    session_runtime::SharedPassphrase,
    storage::{CacheBytes, Session},
    ui::{Ui, UiCommand},
};
use openmates_sdk::view_model::{self as core_view, RequestId, RevocationHandle, ViewCommand, ViewCore};
use ratatui::{Terminal, backend::CrosstermBackend};
use std::{
    io::{self, IsTerminal, Write},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{mpsc, watch};
use tokio_util::sync::CancellationToken;
use zeroize::{Zeroize, Zeroizing};

#[path = "runtime_core_host.rs"]
mod core_host;
#[path = "runtime_send_stream.rs"]
mod send_stream;
#[path = "runtime_offline.rs"]
mod offline;
#[cfg(target_os = "linux")]
#[path = "runtime_benchmark_identity.rs"]
mod benchmark_identity;
#[path = "runtime_saved_send_admissions.rs"]
mod saved_send_admissions;

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

// The UI receives an opaque, read-only file lane and bounded publications.
// It never receives the live Client, credentials or file/key authority.
#[derive(Clone)]
struct NativeCachedChatViews {
    views: std::sync::Arc<CachedChatFileReader>,
    store_generation: RuntimeStoreGeneration,
    security: u64,
}
struct NativeCachedChatPublication {
    publication: CachedChatFilePublication,
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
enum MonitorAdmission { Ready, Offline(Error), Denied(Error) }
impl NativeCachedChatViews {
    async fn publish(&self, id: &str, epoch: Stamp, cancel: CancellationToken) -> Result<Option<Reply>> {
        if self.security != epoch.security || !self.store_generation.is_current() {
            return Err(Error::Cancelled);
        }
        let Some(publication) = self.views.clone().read(id.to_owned(), cancel).await? else { return Ok(None); };
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
/// Paint a core window reply. A force-logout, revocation or owner change may
/// arrive while the reply waits in the bounded channel: the late fence drops
/// it, and a rejected open completion also hides the cached chat.
fn apply_window(ui: &mut Ui, window: core_host::Fenced<core_view::ChatWindowRecord>) {
    use core_view::ChatWindowSource as Source;
    let source=window.value.source;
    match window.into_inner().and_then(|record| {
        let chat = core_host::chat_from_window(&record)?;
        if matches!(source, Source::Canonical | Source::Live | Source::LiveSettled) {
            ui.update_saved_queue_labels(&record);
        }
        Ok(chat)
    }) {
        Ok(chat)=>match source {
            Source::Cached|Source::FirstPage=>ui.set_cached_chat(chat),
            Source::CacheSettled=>ui.set_settled_chat(chat),
            Source::Canonical if chat.messages.is_empty() => {
                ui.set_chat(chat);
                ui.set_status("This saved chat has no messages");
            }
            Source::Canonical=>ui.set_chat(chat),
            Source::CachedOffline=>ui.set_cached_chat_offline(chat),
            Source::Live=>ui.apply_live_selection(ChatSelectionUpdate::Updated(chat)),
            Source::LiveSettled=>ui.apply_live_selection(ChatSelectionUpdate::CacheSettled(chat)),
        },
        Err(_) if matches!(source,Source::FirstPage|Source::CacheSettled|Source::Canonical)=>ui.hide_cached_chat(),
        Err(_)=>{},
    }
}
/// Monitor denials apply only to the original security epoch and monitor.
fn apply_monitor_denial(ui: &mut Ui, current: Stamp, origin: Stamp, error: Error, lifetime: &CancellationToken) -> bool {
    if current.security != origin.security || lifetime.is_cancelled()
        || !matches!(error, Error::Expired | Error::Authentication | Error::Forbidden)
    {
        return false;
    }
    ui.clear_private();
    ui.set_error(&error.to_string());
    true
}
fn apply_cached_chat(ui: &mut Ui, publication: NativeCachedChatPublication) -> bool {
    // Optional cache display never suppresses the queued canonical read. An old
    // owner/lifetime/generation is simply ineligible for this immediate preview.
    if let Ok(window) = publication.into_window() {
        ui.set_cached_chat(window.chat);
        true
    } else {
        false
    }
}

enum View {
    /// Cached display name for the first paint (before authentication).
    Greeting(String),
    Inspirations(Vec<openmates_sdk::client::overview::inspirations::Inspiration>),
    AdmittedAuth(NativeAuthPublication),
    OfflineAuth(NativeAuthPublication, Vec<Item>, Option<u64>),
    OfflineWindow(NativeCachedChatPublication),
    RetryOffline,
    #[cfg(test)]
    Auth {
        username: String,
        expires_at: Option<u64>,
    },
    SignedOut,
    Unlock,
    Items(Workspace, Vec<Item>, Option<u64>),
    /// A core chat window (cached, first page, strict, offline or live).
    Window(core_host::Fenced<core_view::ChatWindowRecord>),
    /// The chat list of a live update (selection kept by id).
    LiveItems(core_host::Fenced<(Vec<Item>, Option<u64>)>),
    /// The open chat became unreadable.
    ChatUnavailable(String),
    CachedChat(NativeCachedChatPublication),
    ChatOpenFailed(Error),
    Sent { request: RequestId, chat: Chat, message_ids: [Option<String>; 2] },
    SendQueued { request: RequestId, chat_id: String, message_id: Option<String>, mode: Option<openmates_sdk::SendQueueMode> },
    SendFailed { request: RequestId, error: Error },
    StopResult { request: RequestId, result: Result<()> },
    Monitor(Error, CancellationToken),
    AccessDenied(ChatMonitorAccessDenial, CancellationToken),
    Item(Workspace, Item),
    Stream { request: RequestId, update: StreamUpdate },
    PairUri(String),
    PairPin,
    Share(String),
    MutationSucceeded,
    Status(&'static str),
    Failed(Error),
    Done,
}
/// Each streamed send needs its own core request id; follow-ups share a view epoch.
static SEND_REQUEST_IDS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
#[derive(Clone, Copy, Default, PartialEq, Eq)]
struct Stamp {
    security: u64,
    view: u64,
}
// One opportunistic cached paint for an admitted Open that had no reader yet.
// This stores selectors/lifetime only; SDK publications retain actual authority.
type CachedRead = futures_util::future::BoxFuture<'static, Result<Option<Reply>>>;
struct PendingCachedSelection { id:String,epoch:Stamp,request:CancellationToken }
impl Drop for PendingCachedSelection {
    fn drop(&mut self) { self.request.cancel(); }
}
impl PendingCachedSelection {
    fn read(&self, reader: NativeCachedChatViews) -> CachedRead {
        let (id, epoch, token) = (self.id.clone(), self.epoch, self.request.clone());
        Box::pin(async move { reader.publish(&id, epoch, token).await })
    }
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
        self.epoch==reply.epoch&&(matches!(&reply.view,View::Window(window) if completes_open(window.value.source))
            ||matches!(&reply.view,View::ChatOpenFailed(_)|View::Sent { .. }|View::Item(..)|View::MutationSucceeded|View::Done))
    }
}
/// Window sources that settle an open (a cached or first page still refreshes).
fn completes_open(source: core_view::ChatWindowSource) -> bool {
    use core_view::ChatWindowSource::*;
    matches!(source, Canonical | CacheSettled | CachedOffline)
}
fn is_live(source: core_view::ChatWindowSource) -> bool {
    matches!(source, core_view::ChatWindowSource::Live | core_view::ChatWindowSource::LiveSettled)
}
struct Reply {
    epoch: Stamp,
    view: View,
}
impl Stamp {
    fn accepts(self, reply: &Reply) -> bool {
        let view_bound = match &reply.view {
            View::ChatOpenFailed(Error::Expired | Error::Authentication | Error::Forbidden) => false,
            View::Window(window) => !is_live(window.value.source),
            View::CachedChat(_) | View::OfflineWindow(_) | View::ChatOpenFailed(_) | View::Item(..) | View::Share(_) | View::MutationSucceeded => true,
            _ => false,
        };
        reply.epoch.security == self.security && (reply.epoch.view == self.view || !view_bound)
    }
}
enum Work {
    Boot,
    OfflineExpired,
    /// The slow part of boot (global recovery + list). Runs only when the
    /// request queue is idle and yields to a chat Open/Send (preempted).
    BootSync,
    /// The optional home banner read. Runs only when the queue is idle after
    /// boot sync, so it never delays or adds to the boot request budget.
    Inspirations,
    Command(UiCommand),
    PairPoll,
    Monitor,
    Live,
    /// A streamed send ended: publish its sent chat or settle its error.
    Send { request: RequestId, chat_id: Option<String>, text: String, turn_cancel: CancellationToken },
    StopReply { request: RequestId, chat_id: String, task_id: String },
    SendFinished(RequestId, Box<Result<openmates_sdk::view_model::SendReceipt>>),
}
type BackgroundReadPreempt = std::sync::Arc<std::sync::Mutex<Option<CancellationToken>>>;
/// Interactive chat reads and sends take priority over optional background reads.
fn preempts_background_read(command: &UiCommand) -> bool {
    matches!(
        command,
        UiCommand::Open(Workspace::Chats, _) | UiCommand::Refresh(Workspace::Chats) | UiCommand::LoadMoreChats | UiCommand::Send { .. }
    )
}
fn track_background_read(slot: &BackgroundReadPreempt, token: &CancellationToken) {
    if let Ok(mut slot) = slot.lock() {
        *slot = Some(token.clone());
    }
}
fn preempt_background_read(slot: &BackgroundReadPreempt) {
    if let Some(token) = slot.lock().ok().and_then(|mut slot| slot.take()) {
        token.cancel();
    }
}
fn register_boot_sync(slot: &BackgroundReadPreempt, requests: &mpsc::Receiver<Request>) -> CancellationToken {
    let token = CancellationToken::new();
    track_background_read(slot, &token);
    // The actor might have observed an empty queue before this branch won.
    // A request queued before the token was published already takes priority.
    if !requests.is_empty() {
        token.cancel();
    }
    token
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
    let mut send_cancellations = std::collections::HashMap::<RequestId, CancellationToken>::new();
    let mut send_admissions = saved_send_admissions::SavedSendAdmissions::default();
    let (requests, receiver) = mpsc::channel(32);
    let (priority, controls) = mpsc::unbounded_channel();
    let (consent, decisions) = mpsc::unbounded_channel();
    let (replies, mut updates) = mpsc::channel(128);
    let (cached_sender, mut cached_views) = watch::channel(None::<NativeCachedChatViews>);
    let stop = CancellationToken::new();
    let demo = args.demo;
    // Cancels a running background BootSync so a chat Open/Send runs first.
    let background_read_preempt: BackgroundReadPreempt = Default::default();
    let actor_preempt = background_read_preempt.clone();
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
    let mut authenticated_frame_reported = false;
    #[cfg(target_os = "linux")]
    let mut benchmark_identity = benchmark_identity::BenchmarkIdentity::from_private_environment();
    let mut offline_personal = false;
    let mut staged_chat_items = None;
    let mut monitor_retry = None;
    let mut membership_check = None;
    let mut clipboard = None;
    let mut pending_cached_selection:Option<PendingCachedSelection>=None;
    let mut pending_cached_read: Option<CachedRead> = None;
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
                if std::mem::take(&mut offline_personal) {
                    monitor_retry=None;membership_check=None;ui.set_authenticated(false);ui.set_unlock_required(true);
                    let _=priority.send(Request{epoch,work:Work::OfflineExpired,cancel:active.clone()});
                    Vec::new()
                } else { vec![UiCommand::Logout] }
            },
            _ = async { #[cfg(unix)] { terminate.recv().await; } #[cfg(not(unix))] { std::future::pending::<()>().await; } } => break,
            _ = async { #[cfg(unix)] { hangup.recv().await; } #[cfg(not(unix))] { std::future::pending::<()>().await; } } => break,
            // Idle terminals have no paint deadline. Resume the existing frame
            // limiter only when input or a client update changes the view.
            _ = render_tick.tick(), if dirty => {
                if dirty {
                    execute!(terminal.backend_mut(), BeginSynchronizedUpdate)?;
                    let painted_result = terminal.draw(|frame| ui.draw(frame)).map(|_|());
                    // Queue the private tag before releasing this frame to the
                    // PTY. The harness joins it only after seeing the end marker.
                    #[cfg(target_os = "linux")]
                    if painted_result.is_ok() && let Some(probe) = benchmark_identity.as_mut() {
                        probe.painted(authenticated.then(|| ui.selected_chat_id()).flatten());
                    }
                    let ended = execute!(terminal.backend_mut(), EndSynchronizedUpdate);
                    painted_result?; ended?;
                    terminal.backend_mut().flush()?;
                    if authenticated && !authenticated_frame_reported {
                        openmates_sdk::startup_diagnostics::StartupPhase::AuthenticatedFrame.record(&Ok(()));
                    }
                    authenticated_frame_reported = authenticated;
                    dirty=false; painted=true;
                }
                // Read detection runs while painting (feature.chat-unread@1).
                ui.take_deferred_commands()
            },
            _ = auth_tick.tick(), if !demo => {
                if !offline_personal && expires_at.is_some_and(|deadline| deadline <= now_ms()) {
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
                    pending_cached_read = pending_cached_selection.as_ref().zip(current)
                        .map(|(selection, reader)| selection.read(reader));
                }
                Vec::new()
            },
            result = async {
                match pending_cached_read.as_mut() {
                    Some(read) => read.await,
                    None => std::future::pending().await,
                }
            }, if !demo && pending_cached_read.is_some() => {
                pending_cached_read = None;
                if pending_cached_selection.as_ref().is_some_and(|selection| selection.is_current(epoch, authenticated))
                    && let Ok(Some(reply)) = result
                    && epoch.accepts(&reply)
                    && let View::CachedChat(publication) = reply.view
                {
                    if apply_cached_chat(&mut ui, publication) {
                        pending_cached_selection = None;
                        dirty = true;
                    }
                }
                Vec::new()
            },
            reply = updates.recv(), if !demo => {
                let Some(reply)=reply else { return Err(Error::Io) };
                if !epoch.accepts(&reply){continue}
                if pending_cached_selection.as_ref().is_some_and(|selection|selection.is_completed_by(&reply)){pending_cached_selection=None;}
                let mut effects=Vec::new();
                let mut ready_send = None;
                match reply.view {
                    View::AdmittedAuth(publication)=>{
                        let Ok((username,deadline))=publication.into_auth() else { continue; };
                        if let Some((items,total))=staged_chat_items.take(){ ui.set_chat_total(total);ui.set_items(Workspace::Chats,items); }
                        offline_personal=false;
                        authenticated=true;ui.set_authenticated(true);ui.set_username(&username);ui.set_settings_restricted(deadline.is_some());expires_at=deadline;pairing=false;membership_check=Some(tokio::time::Instant::now()+Duration::from_secs(30));ui.set_status("Signed in · native encrypted session");
                    },
                    View::OfflineAuth(publication, items, total)=>{
                        let Ok((username,deadline))=publication.into_auth() else { continue; };
                        staged_chat_items=None;
                        offline_personal=true;authenticated=true;ui.set_authenticated(true);ui.set_username(&username);
                        ui.set_settings_restricted(true);ui.set_chat_total(total);ui.set_items(Workspace::Chats,items);
                        expires_at=deadline;ui.set_status("Offline · saved chats are read-only");
                        monitor_retry=Some(tokio::time::Instant::now()+Duration::from_secs(3));
                    },
                    View::OfflineWindow(publication)=>if let Ok(window)=publication.into_window(){ui.set_cached_chat_offline(window.chat);},
                    View::RetryOffline=>if offline_personal {monitor_retry=Some(tokio::time::Instant::now()+Duration::from_secs(3));},
                    #[cfg(test)]
                    View::Auth{username,expires_at:deadline}=>{authenticated=true;ui.set_authenticated(true);ui.set_username(&username);expires_at=deadline;pairing=false;membership_check=Some(tokio::time::Instant::now()+Duration::from_secs(30));ui.set_status("Signed in · native encrypted session");},
                    View::SignedOut=>{offline_personal=false;staged_chat_items=None;close_cached_views(&cached_views);drop(send_admissions.clear());authenticated=false;ui.clear_private();ui.set_authenticated(false);ui.set_status("Signed out");expires_at=None;pairing=false;monitor_retry=None;membership_check=None;},
                    View::Unlock => {
                        if !authenticated {
                            ui.set_unlock_required(true);
                        }
                    },
                    View::Greeting(name)=>if authenticated {ui.set_username_hint(&name);},
                    View::Inspirations(list)=>ui.set_inspirations(list),
                    View::Items(workspace, items, total_count) => {
                        if workspace == Workspace::Chats && !authenticated {
                            staged_chat_items=Some((items,total_count));
                        } else {
                            if workspace == Workspace::Chats { ui.set_chat_total(total_count); }
                            ui.set_items(workspace, items);
                        }
                    },
                    View::Window(window)=>{
                        // Disarm opportunistic old-cache paint before accepting
                        // a fresh first page. This remains read-only/loading.
                        if window.value.source==core_view::ChatWindowSource::FirstPage {pending_cached_selection=None;}
                        apply_window(&mut ui,window);
                    },
                    View::LiveItems(list) => {
                        if let Ok((items, total_count)) = list.into_inner() {
                            ui.set_chat_total(total_count);
                            ui.apply_live_chat_items(items);
                        }
                    },
                    View::ChatUnavailable(chat_id)=>ui.apply_live_selection(ChatSelectionUpdate::Unavailable{chat_id}),
                    View::CachedChat(publication)=>{ apply_cached_chat(&mut ui, publication); },
                    View::SendQueued{request,chat_id,message_id,mode}=>{
                        send_cancellations.remove(&request);
                        ui.send_queued(request,&chat_id,message_id.as_deref(),mode);
                        ready_send = send_admissions.complete(request);
                    },
                    View::Sent{request,chat,message_ids}=>{
                        send_cancellations.remove(&request);
                        ui.send_finished(request,chat,reply.epoch.view==epoch.view,&message_ids);
                        ready_send = send_admissions.complete(request);
                    },
                    View::StopResult{request,result}=>{if reply.epoch.view==epoch.view{ui.stop_result(request,result);}},
                    View::SendFailed{request,error}=>{
                        send_cancellations.remove(&request);
                        if matches!(error,Error::Unavailable{code:"completion_recovery_checkpoint_invalid",..}) {
                            ui.send_failed(request,"Local completion checkpoint is invalid; encrypted data was preserved.");
                        } else { ui.send_failed(request,&error.to_string()); }
                        saved_send_admissions::retain_waiting_after_failure(&mut send_admissions, &mut ui, &mut send_cancellations, request);
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
                        if apply_monitor_denial(&mut ui,epoch,reply.epoch,error,&lifetime){close_cached_views(&cached_views);authenticated=false;effects.push(UiCommand::Logout);}
                        else {
                            ui.mark_cached_chat_offline();
                            ui.set_status("Offline · reconnecting…");
                            // A failed unlock drops its passphrase. Only an already
                            // admitted shell can reconnect without another unlock.
                            monitor_retry = authenticated.then(|| tokio::time::Instant::now() + Duration::from_secs(3));
                        }
                    },
                    View::Item(workspace,item)=>ui.set_item(workspace,item),
                    View::Stream{request,update}=>{
                        ready_send = send_admissions.observe(request, &update);
                        ui.stream_for(request,update,reply.epoch.view==epoch.view);
                    },
                    View::PairUri(uri)=>{pairing=true;ui.set_pairing(&uri);},
                    View::PairPin=>ui.set_pair_pin_required(),
                    View::Share(uri)=>ui.set_share_url(&uri),
                    View::MutationSucceeded=>ui.mutation_succeeded(),
                    View::Status(message)=>ui.set_status(message),
                    View::Failed(error)|View::ChatOpenFailed(error)=>{
                        if !authenticated { staged_chat_items=None; }
                        if matches!(error,Error::Unavailable{code:"completion_recovery_checkpoint_invalid",..}) {
                            ui.set_error("Local completion checkpoint is invalid; encrypted data was preserved.");
                        } else {ui.set_error(&error.to_string());}
                        if matches!(error,Error::Expired|Error::Authentication|Error::Forbidden){pairing=false}
                    },
                    View::Done=>{ui.set_busy(false);pair_poll_pending=false;},
                }
                if let Some(work) = ready_send
                    && saved_send_admissions::dispatch_released(
                        &mut send_admissions, &mut ui, &mut send_cancellations, &requests, work,
                    )
                {
                    preempt_background_read(&background_read_preempt);
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
                UiCommand::StopSend { request, task } => {
                    if let Some((chat_id, task_id)) = task {
                        let stop = Request {
                            epoch, work: Work::StopReply { request, chat_id, task_id },
                            cancel: active.clone(),
                        };
                        if priority.send(stop).is_err() { ui.stop_result(request, Err(Error::Offline)); }
                    } else if send_admissions.cancel_waiting(request) {
                        send_cancellations.remove(&request);
                        ui.send_failed(request, "Follow-up stopped before sending.");
                    } else if let Some(cancel) = send_cancellations.get(&request) {
                        cancel.cancel();
                        ui.set_status("Stopping this local response…");
                    }
                }
                UiCommand::Cancel => {
                    ui.hide_cached_chat();
                    active.cancel();
                    send_cancellations.clear();
                    for pending in send_admissions.clear() {
                        ui.send_failed(pending, "Follow-up cancelled before sending.");
                    }
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
                    // A follow-up into the chat that is streaming keeps the view epoch:
                    // the first send's replies stay current.
                    let followup = matches!(&command, UiCommand::Send { chat_id, .. } if ui.is_streaming_chat(chat_id.as_deref()));
                    if !followup && matches!(
                        command,
                        UiCommand::Open(..) | UiCommand::Refresh(_) | UiCommand::Send { .. }
                    ) {
                        epoch.view = epoch.view.wrapping_add(1);
                    }
                    let preempt_background = preempts_background_read(&command);
                    if matches!(
                        command,
                        UiCommand::Logout
                            | UiCommand::SwitchTeam(_)
                            | UiCommand::Login { .. }
                            | UiCommand::BeginPair
                            | UiCommand::Unlock { .. }
                    ) {
                        close_cached_views(&cached_views);
                        staged_chat_items=None;
                        active.cancel();
                        send_cancellations.clear();
                        drop(send_admissions.clear());
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
                    // Race the selected file against canonical open on independent
                    // lanes. A removed selection cancels its own file read only.
                    pending_cached_selection=None;
                    pending_cached_read=None;
                    if let UiCommand::Open(Workspace::Chats, id) = &command {
                        ui.hide_cached_chat();
                        ui.set_status("Opening saved chat…");
                        if authenticated {
                            let selection = PendingCachedSelection { id: id.clone(), epoch, request: active.child_token() };
                            pending_cached_read = cached_views.borrow().clone().map(|reader| selection.read(reader));
                            pending_cached_selection = Some(selection);
                        }
                    }
                    if !matches!(command, UiCommand::MarkRead(_)) { ui.set_busy(true); }
                    let critical = matches!(command, UiCommand::Logout | UiCommand::SwitchTeam(_));
                    #[cfg(target_os = "linux")]
                    let benchmark_selection = match &command {
                        UiCommand::Open(Workspace::Chats, id) if authenticated && benchmark_identity.is_some() => Some(id.clone()),
                        _ => None,
                    };
                    let (work, send_id) = match command {
                        UiCommand::Send { chat_id, text } => {
                            let request = RequestId(SEND_REQUEST_IDS.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
                            ui.register_send(request, chat_id.as_deref(), &text, followup);
                            let turn_cancel = active.child_token();
                            send_cancellations.insert(request, turn_cancel.clone());
                            (Work::Send { request, chat_id, text, turn_cancel }, Some(request))
                        }
                        other => (Work::Command(other), None),
                    };
                    let request = Request { epoch, work, cancel: active.clone() };
                    let Some(request) = send_admissions.stage(request) else {
                        dirty = true;
                        continue;
                    };
                    let delivered = if critical {
                        priority.send(request).is_ok()
                    } else {
                        requests.try_send(request).is_ok()
                    };
                    if delivered && preempt_background {
                        preempt_background_read(&background_read_preempt);
                    }
                    #[cfg(target_os = "linux")]
                    if delivered && let (Some(probe), Some(id)) = (&benchmark_identity, benchmark_selection) {
                        probe.selected(&id);
                    }
                    if !delivered {
                        pending_cached_selection=None;
                        let error = "The client is busy. Cancel the current operation and retry.";
                        if let Some(request) = send_id {
                            send_cancellations.remove(&request);
                            ui.send_failed(request, error);
                            saved_send_admissions::retain_waiting_after_failure(
                                &mut send_admissions, &mut ui, &mut send_cancellations, request,
                            );
                        }
                        else { ui.set_error(error); }
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
        // The synthetic demo has no server-side unread counter to clear.
        UiCommand::MarkRead(_) => {}
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
        let session = actor.core.client().session().ok_or(Error::Authentication)?;
        let owner = ["id", "user_id"]
            .into_iter()
            .filter_map(|key| actor.core.client().user()[key].as_str())
            .find(|owner| !owner.is_empty())
            .ok_or(Error::Authentication)?;
        Ok(Self {
            store: actor.store.clone(),
            passphrase: actor.passphrase.get(),
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
    /// The core view-model actor state: the one Client, its session runtime
    /// and the credential backend (lane L6b). Chat list start, boot sync,
    /// refresh, team switch and logout run in the core (`core_host.rs`).
    core: send_stream::CoreCell,
    /// Where streamed sends report their end (`Work::SendFinished`).
    send_finished: mpsc::UnboundedSender<send_stream::SendOutcome>,
    /// Set when this request spawned a send stream: its `Done` comes with the
    /// stream's `SendFinished`, not with the admission.
    send_streaming: bool,
    store: RuntimeStore,
    passphrase: SharedPassphrase,
    pair_phase: u8,
    /// Delivery task of a dropped send's queued stream updates (core send).
    relay: core_host::RelaySlot,
    explicit_api: Option<String>,
    explicit_app: Option<String>,
    installed_app: Option<(String, String)>,
    trusted_path: Option<std::path::PathBuf>,
    trusted_verified: bool,
    // Retained across dropped/canceled read futures; cleared only after
    // publication or selected-instance/context invalidation.
    live_pending: Option<ChatInvalidation>,
    live_lifetime: Option<CancellationToken>,
    live_epoch: Stamp,
    live_cancel: CancellationToken,
    live_retry_at: Option<tokio::time::Instant>,
    live_retry_delay: Duration,
    // Root merges the explicit foreground recovery-pump adapter at this seam.
    // These bounded IDs grant no claim/lease and are never interpreted by UI.
    recovery_hints: std::collections::BTreeSet<String>,
    recovery_start_needed: bool,
    recovery_blocked: bool,
    recovery_retry_at: Option<tokio::time::Instant>,
    last_live_hint: Option<ChatInvalidation>,
    cached_views: watch::Sender<Option<NativeCachedChatViews>>,
    cached_views_blocked: bool,
    offline_personal: Option<offline::OfflinePersonal>,
    offline_expected: Option<openmates_sdk::client::NativePersonalOfflineReceipt>,
}
async fn finish_admitted_startup_cohort(
    reconciled: Result<()>,
    current: impl Fn() -> bool,
    hydration: impl std::future::Future<Output = Result<()>>,
) -> Result<()> {
    use openmates_sdk::startup_diagnostics::StartupPhase;

    if !matches!(reconciled, Ok(()) | Err(Error::Protocol | Error::Offline)) {
        return reconciled;
    }
    if !current() {
        return Err(Error::Cancelled);
    }
    let hydrated = hydration.await;
    StartupPhase::Hydrate.record(&hydrated);
    if matches!(
        hydrated,
        Err(Error::Authentication | Error::Expired | Error::Forbidden | Error::VerificationRequired | Error::Cancelled)
    ) {
        return hydrated;
    }
    if !current() {
        return Err(Error::Cancelled);
    }
    reconciled.and(hydrated)
}

async fn actor(
    args: Args,
    mut requests: mpsc::Receiver<Request>,
    controls: mpsc::UnboundedReceiver<Request>,
    decisions: mpsc::UnboundedReceiver<(String, Vec<String>)>,
    replies: mpsc::Sender<Reply>,
    cached_views: watch::Sender<Option<NativeCachedChatViews>>,
    stop: CancellationToken,
    background_read_preempt: BackgroundReadPreempt,
) {
    let (send_finished, mut finished) = mpsc::unbounded_channel();
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
        client.set_parallel_chat_turns(true);
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
        let store = RuntimeStore::new(Some(profile.state_dir), args.encrypted_vault).await?;
        let passphrase = SharedPassphrase::default();
        let mut core = ViewCore::new(client, store.shell().clone(),
            openmates::session_runtime::shared_credentials(&store, passphrase.clone()));
        core.set_eager_cached_content(false);
        core.enable_recently_opened_chats();
        Ok::<_, Error>(Actor {
            core: send_stream::CoreCell::new(core),
            send_finished,
            send_streaming: false,
            trusted_path,
            trusted_verified: false,
            live_pending: None,
            live_lifetime: None,
            live_epoch: Stamp::default(),
            live_cancel: CancellationToken::new(),
            live_retry_at: None,
            live_retry_delay: Duration::from_secs(2),
            recovery_hints: Default::default(),
            recovery_start_needed: true,
            recovery_blocked: false,
            recovery_retry_at: None,
            last_live_hint: None,
            cached_views,
            cached_views_blocked: false,
            offline_personal: None,
            offline_expected: None,
            store,
            passphrase,
            pair_phase: 0,
            relay: Default::default(),
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
    let mut controls = fenced_controls(controls, state.core.revocation_handle(), replies.clone());
    state.core.client_mut().set_consent_receiver(decisions);
    // Mailbox tick performs no network on an idle connection. Reads remain in
    // the keyless SDK task; control/request work always wins actor admission.
    let mut live_tick = tokio::time::interval(Duration::from_millis(250));
    live_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut boot_sync: Option<Stamp> = None;
    let mut inspirations: Option<Stamp> = None;
    while let Some(request) = { state.core.release(); tokio::select! {
        biased;
        _=stop.cancelled()=>None,
        request=controls.recv()=>request,
        request=requests.recv()=>request,
        // Only when no command is queued: a chat Open never waits behind it.
        _=std::future::ready(()), if boot_sync.is_some() => {
            let token = register_boot_sync(&background_read_preempt, &requests);
            boot_sync.take().map(|epoch| Request { epoch, work: Work::BootSync, cancel: token })
        },
        _=std::future::ready(()), if inspirations.is_some() && boot_sync.is_none() => {
            let token = state.live_cancel.child_token();
            track_background_read(&background_read_preempt, &token);
            inspirations.take().map(|epoch| Request { epoch, work: Work::Inspirations, cancel: token })
        },
        outcome = finished.recv() => outcome.map(|(epoch, request, result)| Request {
            epoch, work: Work::SendFinished(request, Box::new(result)), cancel: CancellationToken::new() }),
        _=live_tick.tick(), if state.core.monitor_valid() && !state.live_cancel.is_cancelled() => {
            let token = state.live_cancel.child_token();
            track_background_read(&background_read_preempt, &token);
            Some(Request { epoch: state.live_epoch, work: Work::Live, cancel: token })
        },
    } } {
        let preemptible = matches!(&request.work, Work::BootSync | Work::Inspirations | Work::Live);
        // Cover input arriving between the ready branch and token registration.
        if preemptible && !requests.is_empty() {
            request.cancel.cancel();
        }
        state.core.acquire().await;
        let background = matches!(&request.work, Work::Live | Work::Inspirations | Work::Command(UiCommand::MarkRead(_)));
        let unlocking_vault = state.pair_phase == 0
            && matches!(&request.work, Work::Command(UiCommand::Unlock { .. }));
        let booting = unlocking_vault || matches!(
            &request.work,
            Work::Boot | Work::Command(UiCommand::Login { .. })
        );
        let syncing = matches!(&request.work, Work::BootSync);
        let loading_inspirations = matches!(&request.work, Work::Inspirations);
        let opening_chat = matches!(&request.work, Work::Command(UiCommand::Open(Workspace::Chats, _)));
        let send_id = match &request.work {
            Work::Send { request, .. } | Work::SendFinished(request, _) => Some(*request),
            _ => None,
        };
        let stop_id = if let Work::StopReply { request, .. } = &request.work { Some(*request) } else { None };
        let epoch = request.epoch;
        let cancel = request.cancel.clone();
        let was_offline = state.offline_personal.is_some();
        let mut result = state.dispatch(request, &replies).await;
        // A send now streams on its own task beside this loop; its end returns
        // as `Work::SendFinished` and is settled below like any request.
        if std::mem::take(&mut state.send_streaming) && result.is_ok() { continue; }
        if preemptible {
            if let Ok(mut slot) = background_read_preempt.lock() { slot.take(); }
        }
        if background && preemptible && result == Err(Error::Cancelled) && cancel.is_cancelled() {
            if loading_inspirations {
                inspirations = Some(epoch);
            }
            continue;
        }
        if syncing {
            // A preempted background sync resumes once the queue is idle again.
            if result == Err(Error::Cancelled) && cancel.is_cancelled() && state.core.client_mut().session().is_some() {
                boot_sync = Some(epoch);
                continue;
            }
            if state.core.client_mut().session().is_some() { inspirations = Some(epoch); }
        }
        if booting && result.is_ok() && state.offline_personal.is_none() && state.core.client_mut().session().is_some() {
            boot_sync = Some(epoch);
        }
        if opening_chat && !was_offline && matches!(result, Err(Error::Forbidden)) {
            let previous = state.core.client().clone_session();
            if let Err(error) = state.invalidate_vault_receipt(previous).await {
                result = Err(error);
            }
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
        let relay = state.relay.lock().unwrap_or_else(std::sync::PoisonError::into_inner).take();
        if let Some(relay) = relay {
            let _ = relay.await;
        }
        // Completed unlock failures already cleared the passphrase. Only a
        // cancelled future that left an eligible save in flight may drain it.
        let drain_unlock = unlocking_vault && cancel.is_cancelled() && state.passphrase.is_some()
            && (state.trusted_path.is_none() || state.trusted_verified);
        if result.is_err()
            && !was_offline && (!unlocking_vault || drain_unlock)
            && result != Err(Error::Expired)
            && state.core.client_mut().session().is_some()
            && state.pair_phase == 0
        {
            // A later request can fail after an earlier refresh rotated its cookie.
            // A native keyring may never answer. Once a security command has
            // cancelled this request, leave its started write ordered in Store
            // and admit the priority command, whose durable fence prevents that
            // old write from publishing after logout.
            if let Err(storage_error) =
                finish_or_cancel(state.persist(), &cancel, Duration::from_secs(2)).await
                && !unlocking_vault
            {
                result = Err(storage_error);
            }
        }
        if opening_chat {
            openmates_sdk::startup_diagnostics::StartupPhase::OpenSelectionCompleted.record(&result);
        }
        if let Err(mut error) = result {
            if unlocking_vault {
                state.passphrase.set(None);
            }
            if matches!(error, Error::Expired) {
                state.passphrase.set(None);
                state.pair_phase = 0;
                let _ = replies
                    .send(Reply {
                        epoch,
                        view: View::SignedOut,
                    })
                    .await;
                let cleanup = state.core.clear_credentials().await;
                let _ = state.core.client_mut().logout().await;
                if let Err(cleanup_error) = cleanup {
                    error = cleanup_error;
                }
            } else if unlocking_vault {
                // Submission consumed the form and its secret. Offer a fresh
                // empty form before showing the original failure.
                let _ = replies.send(Reply { epoch, view: View::Unlock }).await;
            }
            let _ = replies
                .send(Reply {
                    epoch,
                    view: if let Some(request) = send_id { View::SendFailed { request, error } }
                        else if let Some(request) = stop_id { View::StopResult { request, result: Err(error) } }
                        else if opening_chat { View::ChatOpenFailed(error) }
                        else { View::Failed(error) },
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
    state.core.acquire().await;
    state.retire_cached_views();
    state.core.set_chat_monitor(None);
    if let Some(lifetime) = state.live_lifetime.take() {
        lifetime.cancel();
    }
}

/// Announce logout independently of the mutable SDK actor. Authentication or a
/// native keyring call can be in flight while the user signs out; the old
/// profile must already be durably revoked before that actor becomes available.
fn fenced_controls(
    mut incoming: mpsc::UnboundedReceiver<Request>,
    revocation: RevocationHandle<CacheBytes>,
    replies: mpsc::Sender<Reply>,
) -> mpsc::UnboundedReceiver<Request> {
    let (forward, receiver) = mpsc::unbounded_channel();
    tokio::spawn(async move {
        while let Some(request) = incoming.recv().await {
            if matches!(&request.work, Work::Command(UiCommand::Logout))
                && let Err(error) = revocation.revoke().await
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
        let monitor = self.core.chat_monitor();
        let generation = self.store.generation_guard();
        let staged = self.core.client().stage_cached_chat_file_reader(
            monitor, self.store.shell().cache().clone(), CancellationToken::new(),
        );
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
        self.core.client_mut().validate_session().await?;
        use openmates::cli::trusted_account as trusted;
        if login {
            trusted::save(path, self.core.client().user()["id"].as_str().unwrap_or(""))
                .map_err(|_| Error::Forbidden)?;
        } else {
            let expected = trusted::load(path).map_err(|_| Error::Forbidden)?;
            trusted::verify(expected.as_deref(), self.core.client().user())
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
        self.core.persist().await
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
    async fn monitor(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        self.monitor_admission(replies, epoch).await.map(|_| ())
    }
    async fn monitor_admission(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<MonitorAdmission> {
        self.core.begin_client_operation(&self.live_cancel);
        // Periodic membership checks do not reconnect a healthy monitor or
        // manufacture another initial full-refresh event every 30 seconds.
        if self.core.chat_monitor().is_some_and(|m| m.is_valid()) {
            let previous = self.core.client().clone_session();
            let checked = self.core.validate_chat_monitor().await;
            let security = matches!(checked, Err(Error::Expired | Error::Authentication | Error::Forbidden));
            if security || matches!(checked, Err(Error::VerificationRequired)) {
                self.invalidate_vault_receipt(previous).await?;
            }
            let admission = match checked {
                Ok(()) => MonitorAdmission::Ready,
                Err(error) if security => MonitorAdmission::Denied(error),
                Err(error) => MonitorAdmission::Offline(error),
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
        self.core.set_chat_monitor(None);
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
        let previously_stored = self.core.client().clone_session();
        let started = async {
            let mut grant = ForegroundRecoveryGrant::new(self.core.client_mut())?;
            grant.start_chat_monitor(lifetime.clone(), events).await
        }
        .await;
        if matches!(started, Err(Error::Offline)) && self.offline_expected.is_some() {
            return Ok(MonitorAdmission::Offline(Error::Offline));
        }
        if let Ok(monitor) = &started && !self.offline_principal_matches() {
            monitor.close();
            return Err(Error::Expired);
        }
        let security = matches!(&started, Err(Error::Expired | Error::Authentication | Error::Forbidden));
        if security || matches!(started, Err(Error::VerificationRequired)) {
            self.invalidate_vault_receipt(previously_stored).await?;
        }
        if security {
            let error = started.as_ref().err().copied().ok_or(Error::Protocol)?;
            Self::emit(replies, epoch, View::Monitor(error, lifetime.clone())).await?;
        }
        // Cookie rotation and local revocation are still attempted. Any failure
        // propagates as a separate storage error after the security notification.
        self.persist().await?;
        match started {
            Ok(monitor) => {
                self.core.set_chat_monitor(Some(monitor));
                self.cached_views_blocked = false;
                // The monitor admission's exact credential/cache persist has
                // completed. Publish immutable cached data BEFORE recovery or
                // the initial canonical list can occupy the actor.
                self.stage_cached_views(epoch);
                self.live_retry_at = None;
                self.live_retry_delay = Duration::from_secs(2);
                self.recovery_start_needed = true;
                self.recovery_blocked = false;
                self.recovery_retry_at = None;
                self.last_live_hint = None;
                Ok(MonitorAdmission::Ready)
            }
            Err(error) if security => Ok(MonitorAdmission::Denied(error)),
            Err(error) => {
                Self::emit(replies, epoch, View::Monitor(error, lifetime)).await?;
                Ok(MonitorAdmission::Offline(error))
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
            .core
            .chat_monitor()
            .is_some_and(|monitor| monitor.is_valid())
        {
            return Ok(CompletionRecoveryPumpOutcome::default());
        }
        // Existing Team/Direct recovery keeps its original ordinary policy.
        let inventory = inventory && self.core.client_mut().supports_cached_default_chat_list();
        let cancel = self.live_cancel.clone();
        self.core.begin_client_operation(&cancel);
        let mut canonical = RecoveryPersistence::new(self)?;
        let store = self.store.clone();
        let pumped = async {
            let mut grant = ForegroundRecoveryGrant::new(self.core.client_mut())?;
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
                    && self.core.chat_monitor().is_some()
                {
                    match self.core.validate_chat_monitor().await {
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
            .core
            .chat_monitor()
            .is_some_and(|monitor| monitor.is_valid())
        {
            return Ok(());
        }
        if self.live_pending.is_none() {
            self.live_pending = self
                .core
                .chat_monitor()
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
        let selected = self.core.open_chat_id().map(str::to_owned);
        let canonical_changed = self
            .recover_before_view(replies, self.live_epoch, selected, false)
            .await?;
        if revisit && !canonical_changed {
            self.last_live_hint = self.live_pending.take();
            return Ok(());
        }
        if !self.core.chat_monitor().is_some_and(|monitor| monitor.is_valid()) {
            return Ok(());
        }
        let Some(hint) = self.live_pending.as_ref() else {
            return Ok(());
        };
        // Core live read: the open chat is the selected chat; read, exact
        // cache+session save and ACK, commit, then list and window events.
        self.core.begin_client_operation(&self.live_cancel);
        let sink = core_host::TerminalSink::new(replies, self.live_epoch, self.store.generation_guard(), &self.live_cancel).live()
            .owned_by(&self.core, self.core.open_chat_id());
        let refreshed = self.core.refresh_live(hint, &sink, &self.live_cancel).await;
        if refreshed.is_err() {
            openmates::native_chat_open_trace::phase("live.refresh", refreshed);
        }
        match refreshed {
            Ok(()) => {
                self.live_retry_at = None;
                self.live_retry_delay = Duration::from_secs(2);
                self.stage_cached_views(self.live_epoch);
                self.last_live_hint = self.live_pending.take();
                Ok(())
            }
            Err(error @ (Error::Expired | Error::Forbidden))
                if self
                    .core
                    .chat_monitor()
                    .is_some_and(|monitor| !monitor.is_valid()) =>
            {
                self.live_pending.take();
                let denial = self
                    .core
                    .chat_monitor()
                    .ok_or(Error::Cancelled)?
                    .access_denial()?;
                if let Some(denial) = denial {
                    if let ChatMonitorAccessDenial::ChatUnavailable { chat_id } = &denial {
                        self.core.close_chat(chat_id);
                    }
                    self.invalidate_vault_receipt(self.core.client().clone_session()).await?;
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
                    .core
                    .chat_monitor()
                    .is_some_and(|monitor| monitor.is_valid()) =>
            {
                // An ordinary UI Cancel invalidates only this read token.
                // Keep the hint for the next admitted active token. Even a
                // forced outer-future drop leaves live_pending owned by Actor;
                // tick is disabled while live_cancel stays canceled.
                self.core
                    .chat_monitor()
                    .ok_or(Error::Cancelled)?
                    .requeue(self.live_pending.take().ok_or(Error::Cancelled)?)?;
                self.persist().await?;
                Ok(())
            }
            Err(error @ (Error::Offline | Error::Protocol | Error::Io)) => {
                openmates_sdk::startup_diagnostics::StartupPhase::LiveCanonicalRead
                    .record(&Err::<(), _>(error));
                // A failed read has no write retry. Preserve hint until a
                // bounded later canonical read; rotated cookies remain durable.
                self.core
                    .chat_monitor()
                    .ok_or(Error::Cancelled)?
                    .requeue(self.live_pending.take().ok_or(Error::Cancelled)?)?;
                // A retained hint can repeat the same failed response on every
                // retry. Increase the delay until a read or new admission succeeds.
                self.live_retry_at = Some(tokio::time::Instant::now() + self.live_retry_delay);
                self.live_retry_delay = (self.live_retry_delay * 2).min(Duration::from_secs(30));
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
    /// The home banner is optional: a failed read leaves the banner empty and
    /// never fails the actor request.
    async fn home_inspirations(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        if self.core.client().session().is_none() {
            return Ok(());
        }
        match self.core.client_mut().daily_inspirations("en").await {
            Ok(mut list) => {
                list.retain(|inspiration| inspiration.surface == "chats");
                Self::emit(replies, epoch, View::Inspirations(list)).await
            }
            Err(_) => Ok(()),
        }
    }
    async fn pair_poll(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
        cancel: &CancellationToken,
    ) -> Result<()> {
        match self.pair_phase {
            1 => {
                if self.core.client_mut().poll_pair().await? == "approved" {
                    self.pair_phase = 2;
                    Self::emit(replies, epoch, View::PairPin).await?;
                }
            }
            3 if self.core.client_mut().finish_pair().await? => {
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
                self.core.client_mut().clone_session().ok_or(Error::Authentication)?,
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
        self.core.client_mut().acknowledge_pair().await?;
        if cancel.is_cancelled() {
            self.core.clear_credentials().await?;
            let _ = self.core.client_mut().logout().await;
            self.passphrase.set(None);
            self.pair_phase = 0;
            return Err(Error::Cancelled);
        }
        self.pair_phase = 0;
        self.authorized(replies, epoch).await?;
        let items = self.core.client_mut().list(Workspace::Chats).await?;
        self.persist().await?;
        Self::emit(replies, epoch, View::Items(Workspace::Chats, core_view::arrange_chat_list(self.core.client(), items), self.core.client().chat_total_count())).await
    }
    async fn abort_pair(&mut self) -> Result<()> {
        let prepared = self.pair_phase == 4;
        self.pair_phase = 0;
        let cleanup = if prepared {
            self.passphrase.set(None);
            self.core.clear_credentials().await
        } else {
            Ok(())
        };
        let cancelled = self.core.client_mut().cancel_pair().await;
        // Also cover cancellation immediately after relay acknowledgement removed
        // its PairState, before the UI accepted the newly persisted session.
        if prepared {
            let _ = self.core.client_mut().logout().await;
        }
        cleanup?;
        cancelled
    }
    async fn dispatch(&mut self, request: Request, replies: &mpsc::Sender<Reply>) -> Result<()> {
        if self.offline_personal.is_some() {
            if matches!(request.work, Work::Command(UiCommand::Unlock { .. })) {
                self.close_offline_personal();
            } else {
                return self.offline_dispatch(request, replies).await;
            }
        }
        if matches!(&request.work, Work::Command(
            UiCommand::Logout | UiCommand::SwitchTeam(_) | UiCommand::Login { .. }
            | UiCommand::BeginPair | UiCommand::PairPin { .. } | UiCommand::Unlock { .. }
        )) {
            self.retire_cached_views();
        }
        let logout = matches!(&request.work, Work::Command(UiCommand::Logout));
        if !matches!(&request.work, Work::Live | Work::Inspirations | Work::SendFinished(..)) {
            self.live_cancel = request.cancel.clone();
        }
        if matches!(
            &request.work,
            Work::Command(UiCommand::Logout | UiCommand::SwitchTeam(_))
        ) {
            self.core.set_chat_monitor(None);
            self.live_pending.take();
            if let Some(lifetime) = self.live_lifetime.take() {
                lifetime.cancel();
            }
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
        let grace = if matches!(&request.work, Work::BootSync | Work::Inspirations | Work::Live) {
            Duration::ZERO
        } else {
            Duration::from_secs(2)
        };
        let previous_live = matches!(&request.work, Work::Live)
            .then(|| std::mem::replace(&mut self.live_cancel, cancel.clone()));
        let operation = self.process(request, replies);
        let result = if admission {
            operation.await
        } else {
            finish_or_cancel(operation, &cancel, grace).await
        };
        if let Some(previous_live) = previous_live {
            self.live_cancel = previous_live;
        }
        result
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
            Work::OfflineExpired => Box::pin(async { Ok(()) }),
            Work::Boot => Box::pin(async move {
                let _request_cancel = &cancel;
                self.boot(replies, epoch).await
            }),
            Work::BootSync => Box::pin(async move {
                self.core.begin_client_operation(&cancel);
                let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel)
                    .owned_by(&self.core, None);
                let request = RequestId(SEND_REQUEST_IDS.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
                use openmates_sdk::startup_diagnostics::StartupPhase;
                let generation = self.core.shell().ops().guard();
                let resumed = core_view::resume_startup_chat(self, request, &sink, &cancel).await;
                StartupPhase::Resume.record(&resumed);
                let offline = resumed?;
                let reconciled = self.boot_sync(replies, epoch).await;
                StartupPhase::Reconcile.record(&reconciled);
                finish_admitted_startup_cohort(
                    reconciled,
                    || generation.is_current() && !cancel.is_cancelled(),
                    core_view::hydrate_startup_chats(self, offline, &cancel),
                ).await
            }),
            Work::Inspirations => Box::pin(async move {
                self.core.begin_client_operation(&cancel);
                self.home_inspirations(replies, epoch).await
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
            Work::Send { request, chat_id, text, turn_cancel } => Box::pin(async move {
                // Bind the stable request parent after any cancelled startup
                // sync. A send child only stops its own turn, and an existing
                // stream keeps its operation parent.
                self.core.begin_client_operation(&cancel);
                // Core admission completes here. The reply streams beside the
                // actor so another encrypted send can be admitted meanwhile.
                let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel)
                    .sending(&self.relay);
                let lease = self.core.lease();
                let stream = core_view::begin_send_with(self, request, chat_id, text,
                    core_view::SendTurnOptions::default(), sink, &turn_cancel, lease).await?;
                self.core.release();
                self.send_streaming = true;
                send_stream::spawn(stream, self.send_finished.clone(), epoch, request);
                Ok(())
            }),
            Work::StopReply { request, chat_id, task_id } => Box::pin(async move {
                self.core.client_mut().cancel_ai_task(&chat_id, &task_id).await?;
                self.persist().await?;
                Self::emit(replies, epoch, View::StopResult { request, result: Ok(()) }).await
            }),
            Work::SendFinished(request, result) => Box::pin(async move {
                let _request_cancel = &cancel;
                let receipt = (*result)?;
                if receipt.status == openmates_sdk::SendStatus::Queued {
                    return Self::emit(replies, epoch, View::SendQueued {
                        request, chat_id: receipt.chat_id, message_id: receipt.user_message_id,
                        mode: receipt.queue_mode }).await;
                }
                Self::emit(replies, epoch, View::Sent {
                    request, chat: core_host::chat_from_window(&receipt.window)?,
                    message_ids: [receipt.user_message_id, receipt.assistant_message_id],
                }).await
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
                    if self.core.client().session().is_some() {
                        return Err(Error::Invalid(
                            "Sign out before signing in to another account.",
                        ));
                    }
                    self.core.client_mut()
                        .login_password(&email, &password, tfa.as_deref())
                        .await?;
                    if let Err(error) = self.verify_trusted(true).await {
                        let _ = self.core.client_mut().logout().await;
                        self.trusted_verified = false;
                        return Err(error);
                    }
                    if cancel.is_cancelled() {
                        let _ = self.core.client_mut().logout().await;
                        return Err(Error::Cancelled);
                    }
                    if let Err(error) = self
                        .store
                        .begin_session_cancellable(
                            self.core.client_mut().clone_session().ok_or(Error::Authentication)?,
                            cancel.clone(),
                        )
                        .await
                    {
                        let _ = self.core.client_mut().logout().await;
                        return Err(error);
                    }
                    self.passphrase.set(Some(password));
                    if let Err(error) = self.persist().await {
                        let _ = self.core.client_mut().logout().await;
                        self.passphrase.set(None);
                        return Err(error);
                    }
                    if cancel.is_cancelled() {
                        let cleanup = self.core.clear_credentials().await;
                        let _ = self.core.client_mut().logout().await;
                        self.passphrase.set(None);
                        cleanup?;
                        return Err(Error::Cancelled);
                    }
                    // Paint the authenticated shell and let the same
                    // preemptible Rust startup sync used for returning
                    // sessions fetch the list once the UI is ready.
                    self.authorized_admission(replies, epoch).await
                }),
                UiCommand::Unlock { passphrase } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.passphrase.set(Some(passphrase));
                    let result = if self.pair_phase == 4 {
                        self.finish_pair(replies, epoch, &cancel).await
                    } else {
                        self.boot(replies, epoch).await
                    };
                    if result.is_err() {
                        self.passphrase.set(None)
                    }
                    result
                }),
                UiCommand::Logout => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.trusted_verified = false;
                    self.pair_phase = 0;
                    self.passphrase.set(None);
                    // Core logout: local revocation and cleanup with remote
                    // logout, SignedOut always, local error before remote.
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel);
                    core_view::handle(self, ViewCommand::Logout, &sink, &cancel).await
                }),
                UiCommand::Cancel => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.abort_pair().await?;
                    if self.core.client().session().is_some() {
                        self.authorized(replies, epoch).await?;
                        if let Ok(items) = self.core.client_mut().cached_chat_items() {
                            Self::emit(replies, epoch, View::Items(Workspace::Chats, core_view::arrange_chat_list(self.core.client(), items), self.core.client().chat_total_count()))
                                .await?;
                        }
                    } else {
                        Self::emit(replies, epoch, View::SignedOut).await?;
                    }
                    Ok(())
                }),
                UiCommand::BeginPair => Box::pin(async move {
                    let _request_cancel = &cancel;
                    if self.core.client().session().is_some() {
                        return Err(Error::Invalid("Sign out before pairing another account."));
                    }
                    let challenge = self.core.client_mut().begin_pair().await?;
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
                    self.core.client_mut().submit_pair_pin(&pin).await?;
                    self.passphrase.set(vault_passphrase);
                    self.pair_phase = 3;
                    Self::emit(
                        replies,
                        epoch,
                        View::Status("Waiting for the browser to finish pairing…"),
                    )
                    .await
                }),
                UiCommand::SwitchTeam(team) => Box::pin(async move {
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel);
                    core_view::handle(self, ViewCommand::SwitchTeam { team_id: team }, &sink, &cancel).await
                }),
                UiCommand::LoadMoreChats => Box::pin(async move {
                    self.core.begin_client_operation(&cancel);
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel).live()
                        .owned_by(&self.core, None);
                    core_view::load_more_chat_metadata(self, 0, &sink, &cancel).await
                }),
                UiCommand::Refresh(Workspace::Chats) => Box::pin(async move {
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel);
                    core_view::handle(self, ViewCommand::RefreshChats, &sink, &cancel).await
                }),
                UiCommand::Refresh(workspace) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    let items = self.core.client_mut().list(workspace).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(workspace, items, self.core.client().chat_total_count())).await
                }),
                UiCommand::Open(Workspace::Chats, id) => Box::pin(async move {
                    // A preempted background read can leave its cancelled operation
                    // on the client. Bind this request before acquiring its owner lease.
                    self.core.begin_client_operation(&cancel);
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel)
                        .owned_by(&self.core, Some(&id));
                    let command = ViewCommand::OpenChat { request: RequestId(SEND_REQUEST_IDS.fetch_add(1, std::sync::atomic::Ordering::Relaxed)), chat_id: id };
                    use openmates::native_chat_open_trace::phase;
                    phase("open.start", Ok(()));
                    let result = core_view::handle(self, command, &sink, &cancel).await;
                    phase("open.finish", result);
                    result
                }),
                UiCommand::Open(workspace, id) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    let generation = self.store.generation_guard();
                    let view = View::Item(workspace, self.core.client_mut().detail(workspace, &id).await?);
                    self.persist().await?;
                    if !generation.is_current() { return Err(Error::Cancelled); }
                    Self::emit(replies, epoch, view).await
                }),
                UiCommand::MarkRead(chat_id) => Box::pin(async move {
                    let sink = core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel);
                    core_view::handle(self, ViewCommand::MarkRead { chat_id }, &sink, &cancel).await
                }),
                UiCommand::Mutate(mutation) => Box::pin(async move {
                    let _request_cancel = &cancel;
                    self.core.client_mut().set_operation_cancel(cancel.clone());
                    let workspace = match &mutation {
                        Mutation::Create { workspace, .. }
                        | Mutation::Update { workspace, .. }
                        | Mutation::Delete { workspace, .. } => *workspace,
                        Mutation::RunWorkflow { .. } => Workspace::Workflows,
                        Mutation::SetSetting { .. } => Workspace::Settings,
                    };
                    let item = self.core.client_mut().mutate(mutation).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::MutationSucceeded).await?;
                    if workspace == Workspace::Apps
                        && let Some(item) = item
                    {
                        Self::emit(replies, epoch, View::Item(workspace, item)).await?;
                    }
                    let items = self.core.client_mut().list(workspace).await?;
                    self.persist().await?;
                    Self::emit(replies, epoch, View::Items(workspace, if workspace == Workspace::Chats { core_view::arrange_chat_list(self.core.client(), items) } else { items }, self.core.client().chat_total_count())).await
                }),
                UiCommand::Share {
                    chat_id,
                    expires_in,
                    password,
                    include_sensitive,
                } => Box::pin(async move {
                    let _request_cancel = &cancel;
                    let uri = self.core.client_mut()
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
                    self.core.client_mut()
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
#[cfg(test)]
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

    #[tokio::test]
    async fn admitted_startup_cohort_hydrates_after_recoverable_reconciliation() {
        for recoverable in [Error::Protocol, Error::Offline] {
            let called = std::cell::Cell::new(false);
            let result = finish_admitted_startup_cohort(Err(recoverable), || true, async {
                called.set(true);
                Ok(())
            })
            .await;
            assert!(called.get());
            assert_eq!(result, Err(recoverable));
        }
        assert_eq!(
            finish_admitted_startup_cohort(Err(Error::Protocol), || true, async { Err(Error::Expired) }).await,
            Err(Error::Expired),
        );
    }

    #[tokio::test]
    async fn admitted_startup_cohort_skips_hydration_after_denial_or_invalid_generation() {
        for (reconciled, current, expected) in [
            (Err(Error::Forbidden), true, Error::Forbidden),
            (Err(Error::Expired), true, Error::Expired),
            (Err(Error::Cancelled), true, Error::Cancelled),
            (Err(Error::Protocol), false, Error::Cancelled),
        ] {
            let result = finish_admitted_startup_cohort(reconciled, || current, async {
                panic!("startup hydration requires current authority");
            })
            .await;
            assert_eq!(result, Err(expected));
        }
    }

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
        let passphrase = SharedPassphrase::new(Some(Zeroizing::new("fixture passphrase".into())));
        let core = ViewCore::new(Client::new(&session.api_url, Some(session.clone())).unwrap(),
            store.shell().clone(), openmates::session_runtime::shared_credentials(&store, passphrase.clone()));
        let actor = Actor {
            core: send_stream::CoreCell::new(core),
            send_finished: mpsc::unbounded_channel().0,
            send_streaming: false,
            store,
            passphrase,
            pair_phase: 0,
            relay: Default::default(),
            explicit_api: None,
            explicit_app: None,
            installed_app: None,
            trusted_path: None,
            trusted_verified: false,
            live_pending: None,
            live_lifetime: None,
            live_epoch: Stamp::default(),
            live_cancel: CancellationToken::new(),
            live_retry_at: None,
            live_retry_delay: Duration::from_secs(2),
            recovery_hints: Default::default(),
            recovery_start_needed: true,
            recovery_blocked: false,
            recovery_retry_at: None,
            last_live_hint: None,
            cached_views: watch::channel(None).0,
            cached_views_blocked: false,
            offline_personal: None,
            offline_expected: None,
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
            view: core_host::test_window(&Chat { id: "chat".into(), ..Chat::default() }, core_view::ChatWindowSource::Canonical)
        }));
        assert!(!current.accepts(&Reply {
            epoch: Stamp {
                security: 4,
                view: 11
            },
            view: core_host::test_window(&Chat { id: "chat".into(), ..Chat::default() }, core_view::ChatWindowSource::Canonical)
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
            view: core_host::test_window(&Chat { id: "chat".into(), ..Chat::default() }, core_view::ChatWindowSource::Canonical)
        }));
        // A late owned list may populate its cache, but cannot navigate the UI.
        assert!(current.accepts(&Reply {
            epoch: Stamp {
                security: 4,
                view: 11
            },
            view: View::Items(Workspace::Tasks, vec![], None)
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
                .load(actor.passphrase.get())
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
        assert!(actor.core.client().session().is_none());
        assert!(actor.passphrase.is_none());
        assert!(actor.store.load(None).await.unwrap().is_none());
    }
    #[tokio::test]
    async fn another_login_cannot_replace_an_active_owner() {
        let (_directory, mut actor) = fixture().await;
        let original = actor.core.client().session().unwrap().session_id.clone();
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
        assert_eq!(actor.core.client().session().unwrap().session_id, original);
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
        let mut pending = fenced_controls(incoming, actor.core.revocation_handle(), replies);
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
                .load(actor.passphrase.get())
                .await
                .unwrap()
                .is_none()
        );
        assert_eq!(actor.persist().await, Err(Error::Locked));
        assert!(actor.core.client().session().is_some());
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
        assert!(actor.core.client().session().is_none());
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

#[cfg(test)]
#[path = "runtime_send_tests.rs"]
mod send_tests;
#[cfg(test)]
#[path = "runtime_send_stream_tests.rs"]
mod send_stream_tests;
