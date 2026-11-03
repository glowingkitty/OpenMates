//! Native Ratatui presentation and event controller. No JavaScript, process bridge or ANSI parser.
mod apps;
mod editor;
mod markdown;
mod questions;
use crate::model::{Chat, Item, Message, Mutation, StreamUpdate, Workspace};
use crossterm::event::{
    KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use editor::Editor;
use markdown::{Link, Row};
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap},
};
use serde_json::{Value, json};
use unicode_width::UnicodeWidthStr;
use zeroize::Zeroizing;

// Adapted from DESIGN.md's dark grey, global action, and product brand tokens.
const BASE: Color = Color::Rgb(23, 23, 23);
const PANEL: Color = Color::Rgb(33, 33, 33);
const BORDER: Color = Color::Rgb(44, 44, 44);
const TEXT: Color = Color::Rgb(230, 230, 230);
const MUTED: Color = Color::Rgb(192, 192, 192);
const ACCENT: Color = Color::Rgb(255, 85, 59);
const BLUE: Color = Color::Rgb(90, 133, 235);

/// Runtime effects. Deliberately has no Debug implementation: credentials must not enter logs.
pub enum UiCommand {
    Quit,
    Refresh(Workspace),
    Open(Workspace, String),
    Send {
        chat_id: Option<String>,
        text: String,
    },
    Mutate(Mutation),
    Login {
        email: String,
        password: Zeroizing<String>,
        tfa: Option<String>,
    },
    Unlock {
        passphrase: Zeroizing<String>,
    },
    Logout,
    BeginPair,
    PairPin {
        pin: Zeroizing<String>,
        vault_passphrase: Option<Zeroizing<String>>,
    },
    Cancel,
    OpenUrl(String),
    Copy(String),
    SelectionMode(bool),
    Download {
        workspace: Workspace,
        id: String,
        destination: std::path::PathBuf,
        overwrite: bool,
    },
    Share {
        chat_id: String,
        expires_in: u64,
        password: Zeroizing<String>,
        include_sensitive: bool,
    },
    SwitchTeam(Option<String>),
    Consent {
        request_id: String,
        approved_ids: Vec<String>,
    },
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum Focus {
    Navigation,
    Composer,
    Content,
    Sidebar,
}
#[derive(Clone)]
enum HitAction {
    Nav(Workspace),
    Settings,
    Sidebar,
    Open(usize),
    SidebarItem(usize),
    NewChat,
    Composer,
    Back,
    Close,
    DetailTab(usize),
    Edit,
    Create,
    Delete,
    Run,
    Toggle,
    Link(Link),
    Copy,
    FormField(usize),
    FormSubmit,
    FormCancel,
    Palette(usize),
    SettingsRoute(String),
    Login,
    Pair,
    Logout,
    NextCard(i32),
    SettingsEdit,
    Share,
    Download,
    RevealShare,
    CopyShare,
    QrShare,
    DenyConsent,
    SkillRun,
}
struct Hit {
    rect: Rect,
    action: HitAction,
}
struct Field {
    key: String,
    label: String,
    editor: Editor,
    kind: FieldKind,
    required: bool,
}
enum FieldKind {
    Text,
    Secret,
    Multiline,
    Number,
    Bool,
    Choice(Vec<String>),
}
impl Field {
    fn text(key: &str, label: &str, value: &str, required: bool) -> Self {
        Self {
            key: key.into(),
            label: label.into(),
            editor: Editor::from(value),
            kind: FieldKind::Text,
            required,
        }
    }
    fn secret(key: &str, label: &str) -> Self {
        let mut f = Self::text(key, label, "", true);
        f.kind = FieldKind::Secret;
        f
    }
    fn choice(key: &str, label: &str, value: &str, options: Vec<String>) -> Self {
        let mut f = Self::text(key, label, value, true);
        f.kind = FieldKind::Choice(options);
        f
    }
    fn multiline(key: &str, label: &str, value: &str) -> Self {
        let mut f = Self::text(key, label, value, false);
        f.kind = FieldKind::Multiline;
        f
    }
}
enum FormPurpose {
    AppInput(Item),
    AppConfirm {
        skill: Item,
        input: Value,
        draft: Vec<Field>,
    },
    Login,
    Unlock,
    PairPin,
    Create(Workspace),
    Edit(Workspace, String),
    Settings(String),
    Question(Value),
    Delete(Workspace, String),
    Help,
    Palette,
    Pairing,
    Share(String),
    Download(Workspace, String),
    Team,
    ShareResult {
        visible: bool,
        qr: bool,
    },
    Consent {
        request_id: String,
        items: Vec<Item>,
    },
}
struct Form {
    title: String,
    purpose: FormPurpose,
    fields: Vec<Field>,
    selected: usize,
    error: String,
    busy: bool,
    scroll: usize,
    context: Option<String>,
}
impl Form {
    fn new(title: &str, purpose: FormPurpose, fields: Vec<Field>) -> Self {
        Self {
            title: title.into(),
            purpose,
            fields,
            selected: 0,
            error: String::new(),
            busy: false,
            scroll: 0,
            context: None,
        }
    }
}
enum Delivery {
    Staged,
    Submitted { chat_id: String, message_id: String },
    Admitted { chat_id: String, message_id: String },
}
struct UncertainTurn {
    message_id: String,
    text: Zeroizing<String>,
    admitted: bool,
}
/// Header hint next to the workspace tabs (TS `Ctrl+G navigation`).
const NAVIGATION_HINT: &str = "Ctrl+G navigation";
/// Breadcrumb between "‹ Back" and an opened chat's title (TS `‹ Back › Chats › <title>`).
const CHAT_CRUMB: &str = "› Chats › ";
struct ActiveTurn {
    chat_id: String,
    user_id: String,
    assistant: Option<String>,
    expects_reply: bool,
}
struct Settings {
    route: String,
    selected: usize,
    sidebar_before: bool,
    focus_before: Focus,
    scroll_before: usize,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum CachedChatState { Refreshing, Offline, Settled }

pub struct Ui {
    workspace: Workspace,
    task_order: crate::error::Result<openmates_sdk::task_order::TaskOrder>,
    items: [Vec<Item>; 6],
    inspirations: Vec<openmates_sdk::client::overview::inspirations::Inspiration>,
    inspiration_index: usize,
    selected: [usize; 6],
    sidebar: bool,
    focus: Focus,
    navigation_index: usize,
    navigation_return: Focus,
    chat: Option<Chat>,
    // Presentation gate only: cached rows do not settle canonical delivery.
    cached_chat_state: Option<CachedChatState>,
    detail: Option<Item>,
    detail_tab: usize,
    node_selected: usize,
    origin: Option<(Workspace, Item, usize)>,
    chat_origin: Option<(Chat, usize, bool, Option<CachedChatState>)>,
    app_history: Vec<(Item, usize)>,
    draft: Editor,
    drafts: std::collections::HashMap<String, Zeroizing<String>>,
    pending_send: Option<(String, Zeroizing<String>)>,
    active_turn: Option<ActiveTurn>,
    delivery: Delivery,
    uncertain_turns: std::collections::HashMap<String, UncertainTurn>,
    last_uncertain: Option<String>,
    scroll: usize,
    follow_tail: bool,
    hits: Vec<Hit>,
    composer_rect: Rect,
    composer_offset: usize,
    size: (u16, u16),
    status: String,
    authenticated: bool,
    username: String,
    streaming: bool,
    selecting: bool,
    form: Option<Form>,
    settings: Option<Settings>,
    palette_query: Editor,
    chat_layout: Option<(u16, Vec<Row>)>,
    embed_offsets: std::collections::HashMap<String, usize>,
    content_action: usize,
    detail_links: Vec<Link>,
}
fn index(workspace: Workspace) -> usize {
    match workspace {
        Workspace::Chats => 0,
        Workspace::Apps => 1,
        Workspace::Projects => 2,
        Workspace::Workflows => 3,
        Workspace::Tasks => 4,
        Workspace::Settings => 5,
    }
}
fn text_field<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}
fn field_list<'a>(item: &'a Item, key: &str) -> &'a [Value] {
    item.fields
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}
/// Breadcrumb plus bold title when the row has room for both.
fn chat_title_line(title: &str, width: u16) -> Line<'static> {
    let crumb_width = CHAT_CRUMB.width() as u16;
    let title_style = Style::default().fg(TEXT).bold();
    if width > crumb_width + 12 {
        Line::from(vec![
            Span::styled(CHAT_CRUMB, Style::default().fg(MUTED)),
            Span::styled(title.to_owned(), title_style),
        ])
    } else {
        Line::from(Span::styled(title.to_owned(), title_style))
    }
}
fn panel(title: impl Into<String>, focused: bool) -> Block<'static> {
    Block::default()
        .title(title.into())
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(if focused { ACCENT } else { BORDER }))
        .style(Style::default().bg(PANEL).fg(TEXT))
}
fn inset(rect: Rect, h: u16, v: u16) -> Rect {
    Rect::new(
        rect.x + h.min(rect.width),
        rect.y + v.min(rect.height),
        rect.width.saturating_sub(h * 2),
        rect.height.saturating_sub(v * 2),
    )
}
fn center(rect: Rect, width: u16, height: u16) -> Rect {
    let w = rect.width.min(width);
    let h = rect.height.min(height);
    Rect::new(
        rect.x + (rect.width - w) / 2,
        rect.y + (rect.height - h) / 2,
        w,
        h,
    )
}
impl Default for Ui {
    fn default() -> Self {
        Self::new()
    }
}
impl Ui {
    pub fn new() -> Self {
        Self {
            workspace: Workspace::Chats,
            task_order: crate::task_order::for_host(),
            items: std::array::from_fn(|_| vec![]),
            inspirations: vec![],
            inspiration_index: 0,
            selected: [0; 6],
            sidebar: false,
            // TS route("chats","start"): the home cards own focus, so Enter
            // opens the selected chat; typing still starts a draft.
            focus: Focus::Content,
            navigation_index: 0,
            navigation_return: Focus::Composer,
            chat: None,
            cached_chat_state: None,
            detail: None,
            detail_tab: 0,
            node_selected: 0,
            origin: None,
            chat_origin: None,
            app_history: vec![],
            draft: Editor::default(),
            drafts: std::collections::HashMap::new(),
            pending_send: None,
            active_turn: None,
            delivery: Delivery::Staged,
            uncertain_turns: std::collections::HashMap::new(),
            last_uncertain: None,
            scroll: 0,
            follow_tail: true,
            hits: vec![],
            composer_rect: Rect::default(),
            composer_offset: 0,
            size: (0, 0),
            status: "Ready · cached content stays available when offline".into(),
            authenticated: false,
            username: String::new(),
            streaming: false,
            selecting: false,
            form: None,
            settings: None,
            palette_query: Editor::default(),
            content_action: 0,
            detail_links: vec![],
            chat_layout: None,
            embed_offsets: std::collections::HashMap::new(),
        }
    }
    fn draft_key(&self) -> String {
        self.chat
            .as_ref()
            .map(|c| c.id.clone())
            .filter(|id| !id.is_empty())
            .unwrap_or_else(|| "__new__".into())
    }
    fn remember_draft(&mut self) {
        let key = self.draft_key();
        if self.draft.text.is_empty() {
            self.drafts.remove(&key);
        } else {
            self.drafts
                .insert(key, Zeroizing::new(self.draft.text.to_string()));
        }
    }
    fn restore_draft(&mut self) {
        let key = self.draft_key();
        self.draft = self
            .drafts
            .get(&key)
            .map(|value| Editor::from(value))
            .unwrap_or_default();
    }
    fn restore_pending_send(&mut self) {
        let active = self.active_turn.take();
        self.chat_layout = None;
        if let Some((key, text)) = self.pending_send.take() {
            if matches!(self.delivery, Delivery::Staged)
                && let Some(turn) = &active
                && let Some(chat) = self.chat.as_mut().filter(|chat| chat.id == turn.chat_id)
            {
                chat.messages.retain(|message| {
                    message.id != turn.user_id
                        && turn.assistant.as_ref().is_none_or(|id| &message.id != id)
                });
            }
            let delivery = std::mem::replace(&mut self.delivery, Delivery::Staged);
            if !matches!(delivery, Delivery::Staged) {
                let (chat_id, message_id, admitted) = match delivery {
                    Delivery::Submitted {
                        chat_id,
                        message_id,
                    } => (chat_id, message_id, false),
                    Delivery::Admitted {
                        chat_id,
                        message_id,
                    } => (chat_id, message_id, true),
                    Delivery::Staged => unreachable!(),
                };
                self.drafts.remove(&format!("__retry__:{key}"));
                self.drafts.remove(&format!("__retry__:{chat_id}"));
                self.last_uncertain = Some(chat_id.clone());
                self.uncertain_turns.insert(
                    chat_id,
                    UncertainTurn {
                        message_id,
                        text,
                        admitted,
                    },
                );
                self.streaming = false;
                return;
            }
            self.drafts
                .insert(format!("__retry__:{key}"), Zeroizing::new(text.to_string()));
            if self.draft_key() == key {
                if self.draft.text.is_empty() {
                    self.drafts.insert(key, text);
                    self.restore_draft();
                } else {
                    self.remember_draft();
                }
            } else {
                self.drafts.entry(key).or_insert(text);
            }
        }
        self.streaming = false;
    }
    pub fn send_succeeded(&mut self) {
        self.active_turn = None;
        self.chat_layout = None;
        if let Some((key, _)) = self.pending_send.take() {
            self.drafts.remove(&format!("__retry__:{key}"));
            self.uncertain_turns.remove(&key);
        }
        match &self.delivery {
            Delivery::Submitted { chat_id, .. } | Delivery::Admitted { chat_id, .. } => {
                self.uncertain_turns.remove(chat_id);
            }
            Delivery::Staged => {}
        }
        self.delivery = Delivery::Staged;
        self.streaming = false;
    }
    fn new_chat(&mut self) {
        self.remember_draft();
        self.chat = None;
        self.cached_chat_state = None;
        self.detail = None;
        self.origin = None;
        self.chat_origin = None;
        self.app_history.clear();
        self.workspace = Workspace::Chats;
        self.restore_draft();
        self.focus = Focus::Composer;
        self.scroll = 0;
        self.hits.clear();
    }
    pub fn set_items(&mut self, workspace: Workspace, mut items: Vec<Item>) {
        let i = index(workspace);
        let selected_id = (workspace == Workspace::Tasks)
            .then(|| {
                self.items[i]
                    .get(self.selected[i])
                    .map(|item| item.id.clone())
            })
            .flatten();
        if workspace == Workspace::Tasks {
            let result = match &self.task_order {
                Ok(order) => order.sort_items(&mut items),
                Err(_) => Err(crate::error::Error::Invalid(
                    "Task ordering requires a supported explicit host locale.",
                )),
            };
            if let Err(error) = result {
                self.status = error.to_string();
                self.hits.clear();
                return;
            }
        }
        self.items[i] = items;
        self.selected[i] = selected_id
            .and_then(|id| self.items[i].iter().position(|item| item.id == id))
            .unwrap_or_else(|| self.selected[i].min(self.items[i].len().saturating_sub(1)));
        if let Some(detail) = &self.detail
            && self.workspace == workspace
            && let Some(updated) = self.items[i].iter().find(|item| item.id == detail.id)
        {
            self.detail = Some(updated.clone());
        }
        self.hits.clear();
    }
    /// Apply an already authenticated/durable model without navigation side
    /// effects. Composer text, selection, scroll, focus and own-send state stay
    /// owned by this terminal. Recent-list absence alone never closes a chat.
    pub fn apply_live_chat_models(&mut self, models: crate::client::ChatModels) {
        let index = index(Workspace::Chats);
        let selected = self.items[index]
            .get(self.selected[index])
            .map(|item| item.id.clone());
        self.set_items(Workspace::Chats, models.items);
        if let Some(id) = selected
            && let Some(position) = self.items[index].iter().position(|item| item.id == id)
        {
            self.selected[index] = position;
        }
        let cached_settlement = matches!(&models.selection, crate::client::ChatSelectionUpdate::CacheSettled(_));
        match models.selection {
            crate::client::ChatSelectionUpdate::Updated(chat)
            | crate::client::ChatSelectionUpdate::CacheSettled(chat) => {
                if let Some((saved, _, _, cached)) = self.chat_origin.as_mut()
                    && saved.id == chat.id
                {
                    *saved = chat.clone();
                    *cached = cached_settlement.then_some(CachedChatState::Settled);
                }
                if self
                    .chat
                    .as_ref()
                    .is_some_and(|current| current.id == chat.id)
                    && self.pending_send.is_none()
                    && !self.streaming
                {
                    // Own-send optimistic/streaming state remains governed by
                    // existing StreamUpdate/Sent admission fences.
                    let cached_handoff = self.is_cached_chat_read_only();
                    self.chat = Some(chat);
                    self.cached_chat_state = cached_settlement.then_some(CachedChatState::Settled);
                    self.chat_layout = None;
                    self.hits.clear();
                    if cached_settlement { self.set_status("Showing all cached messages · download fetches full history"); }
                    else if cached_handoff { self.set_status("Chat refreshed"); }
                }
            }
            crate::client::ChatSelectionUpdate::Unavailable { chat_id } => {
                if self
                    .chat_origin
                    .as_ref()
                    .is_some_and(|(chat, _, _, _)| chat.id == chat_id)
                {
                    self.chat_origin = None;
                }
                if self
                    .chat
                    .as_ref()
                    .is_some_and(|current| current.id == chat_id)
                {
                    // Preserve unsent local text under its original chat ID.
                    // It must never be silently rebound/submitted as a new chat.
                    self.remember_draft();
                    self.chat = None;
                    self.cached_chat_state = None;
                    self.chat_origin = None;
                    self.chat_layout = None;
                    self.draft = Editor::default();
                    // Do not discard an in-flight own-send receipt or its
                    // retry text. Existing completion/error paths settle it
                    // under the original chat ID; none is rebound here.
                    self.hits.clear();
                    self.status = "Selected chat is no longer available in this scope".into();
                }
            }
            _ => {}
        }
    }
    pub fn hide_live_chat(&mut self, id: &str) {
        let items = self.items[index(Workspace::Chats)]
            .iter()
            .filter(|item| item.id != id)
            .cloned()
            .collect();
        self.apply_live_chat_models(crate::client::ChatModels {
            items,
            selection: crate::client::ChatSelectionUpdate::Unavailable {
                chat_id: id.to_owned(),
            },
        });
    }
    pub fn selected_chat_id(&self) -> Option<&str> {
        self.chat.as_ref().map(|chat| chat.id.as_str())
    }
    /// Accept only the already-admitted bounded SDK cached publication through
    /// the runtime's fenced View handler. No cache may clear delivery guards.
    pub fn set_cached_chat(&mut self, chat: Chat) {
        if !self.authenticated || chat.id.is_empty() {
            return;
        }
        let same = self.chat.as_ref().is_some_and(|current| current.id == chat.id);
        // Never replace an own-send optimistic/streaming transcript with older
        // cached rows. Background sends remain owned under their original ID.
        if same && (!self.is_cached_chat_read_only() || self.streaming || self.pending_send.is_some()) {
            return;
        }
        if !same {
            self.remember_draft();
            // A question belongs to the transcript from which it was opened,
            // unlike the independent delivery/consent journal.
            if self.form.as_ref().is_some_and(|form| matches!(form.purpose, FormPurpose::Question(_))) {
                self.form = None;
            }
            self.set_status("Saved chat selected");
            if self.workspace == Workspace::Projects
                && let Some(item) = self.detail.clone()
            {
                self.origin = Some((self.workspace, item, self.detail_tab));
            }
        }
        self.workspace = Workspace::Chats;
        self.chat = Some(chat);
        self.cached_chat_state = Some(CachedChatState::Refreshing);
        self.detail = None;
        self.chat_layout = None;
        if !same {
            self.embed_offsets.clear();
            self.content_action = 0;
        }
        if !same {
            self.restore_draft();
            self.scroll = 0;
            self.follow_tail = true;
            self.focus = Focus::Composer;
        }
        self.hits.clear();
    }
    /// Source-tagged offline data remains display-only; even an existing
    /// canonical/optimistic transcript cannot turn this result into an ACK.
    pub fn set_cached_chat_offline(&mut self, chat: Chat) {
        if !self.authenticated || chat.id.is_empty() { return; }
        let same = self.chat.as_ref().is_some_and(|current| current.id == chat.id);
        if !same { self.set_cached_chat(chat); }
        if self.chat.is_some() {
            self.cached_chat_state = Some(CachedChatState::Offline);
            self.hits.clear();
        }
    }
    pub fn mark_cached_chat_offline(&mut self) {
        if self.chat.is_some() && self.cached_chat_state.is_some() {
            self.cached_chat_state = Some(CachedChatState::Offline);
        }
        if let Some((_, _, _, state)) = self.chat_origin.as_mut()
            && state.is_some()
        {
            *state = Some(CachedChatState::Offline);
        }
    }
    pub fn is_cached_chat_refreshing(&self) -> bool {
        self.chat.is_some() && self.cached_chat_state == Some(CachedChatState::Refreshing)
    }
    pub fn is_cached_chat_read_only(&self) -> bool {
        self.chat.is_some() && matches!(self.cached_chat_state, Some(CachedChatState::Refreshing | CachedChatState::Offline))
    }
    /// Denial/cancel/expiry hides a preview, preserving draft binding and all
    /// uncertain/accepted-effect state. A bare cached frame is never restored.
    /// A settled cache restores interactive controls only after the SDK's exact
    /// online authorization, durable save and credential ACK. Strict share and
    /// download commands still fetch full history independently.
    pub fn set_settled_chat(&mut self, chat: Chat) {
        if !self.authenticated || chat.id.is_empty() { return; }
        let same = self.chat.as_ref().is_some_and(|current| current.id == chat.id);
        if same && (self.streaming || self.pending_send.is_some()) { return; }
        // A freshly authorized settlement replaces same-ID canonical/cache rows
        // without using set_chat's delivery/uncertainty reconciliation.
        if same {
            self.chat = Some(chat); self.chat_layout = None; self.hits.clear();
        } else { self.set_cached_chat(chat); }
        self.cached_chat_state = Some(CachedChatState::Settled);
        self.set_status("Showing all cached messages · download fetches full history");
    }
    pub fn hide_cached_chat(&mut self) {
        if self.chat_origin.as_ref().is_some_and(|(_, _, _, cached)| cached.is_some()) {
            self.chat_origin = None;
        }
        if self.chat.is_some() && self.cached_chat_state.is_some() {
            self.remember_draft();
            self.chat = None;
            self.cached_chat_state = None;
            self.draft = Editor::default();
            self.chat_layout = None;
            self.embed_offsets.clear();
            self.hits.clear();
        }
    }
    /// The chat whose turn is still running (TS `runningTuiChatGroups`).
    fn running_chat_id(&self) -> Option<String> {
        self.active_turn.as_ref().filter(|_| self.streaming).map(|turn| turn.chat_id.clone())
    }
    fn visible_chat_streaming(&self) -> bool {
        self.streaming && self.active_turn.as_ref().is_some_and(|turn| {
            self.chat.as_ref().is_some_and(|chat| chat.id == turn.chat_id)
        })
    }
    fn cached_action_blocked(&mut self) -> bool {
        if !self.is_cached_chat_read_only() { return false; }
        self.set_status("This cached chat is read-only; wait for a current result before sending, copying, sharing or exporting");
        true
    }
    pub fn set_chat(&mut self, chat: Chat) {
        let cached_handoff = self.is_cached_chat_read_only()
            && self.chat.as_ref().is_some_and(|current| current.id == chat.id);
        let retained_view = cached_handoff.then_some((self.scroll, self.follow_tail, self.focus));
        let other_send_streaming = cached_handoff && self.streaming && self.pending_send.is_some()
            && self.active_turn.as_ref().is_some_and(|turn| turn.chat_id != chat.id);
        self.cached_chat_state = None;

        if self.uncertain_turns.get(&chat.id).is_some_and(|turn| {
            chat.messages
                .iter()
                .any(|message| message.id == turn.message_id && message.role == "user")
        }) {
            self.uncertain_turns.remove(&chat.id);
            if self.last_uncertain.as_ref() == Some(&chat.id) {
                self.last_uncertain = None;
            }
        }
        if self.pending_send.is_none() {
            self.active_turn = None;
        }
        self.remember_draft();
        self.chat_layout = None;
        if !cached_handoff {
            self.embed_offsets.clear();
            self.content_action = 0;
        }
        if self.workspace == Workspace::Projects
            && let Some(item) = self.detail.clone()
        {
            self.origin = Some((self.workspace, item, self.detail_tab));
        }
        self.workspace = Workspace::Chats;
        self.chat = Some(chat);
        if !cached_handoff { self.restore_draft(); }
        self.detail = None;
        self.scroll = 0;
        self.follow_tail = true;
        self.focus = Focus::Composer;
        self.streaming = other_send_streaming;
        if let Some((scroll, follow, focus)) = retained_view {
            self.scroll = scroll; self.follow_tail = follow; self.focus = focus;
        }
        self.hits.clear();
        if cached_handoff { self.set_status("Chat refreshed"); }
    }
    pub fn set_item(&mut self, workspace: Workspace, item: Item) {
        self.remember_draft();
        if workspace == Workspace::Apps {
            if let Some(chat) = self.chat.take() {
                self.chat_origin = Some((chat, self.scroll, self.follow_tail, self.cached_chat_state));
            }
            if let Some(previous) = self.detail.clone() {
                if self.workspace == Workspace::Apps && previous.id != item.id {
                    self.app_history.push((previous, self.detail_tab));
                } else if self.workspace != Workspace::Apps {
                    self.origin = Some((self.workspace, previous, self.detail_tab));
                }
            }
        }
        self.workspace = workspace;
        self.detail = Some(item);
        self.detail_links.clear();
        self.node_selected = 0;
        self.chat = None;
        self.cached_chat_state = None;
        self.restore_draft();
        self.detail_tab = 0;
        self.scroll = 0;
        self.focus = Focus::Content;
        self.hits.clear();
    }
    pub fn set_status(&mut self, status: &str) {
        if status == "Cancelled" {
            self.hide_cached_chat();
            self.restore_pending_send();
        }
        self.status = markdown::clean(status).replace('\n', " ");
        if let Some(turn) = self
            .last_uncertain
            .as_ref()
            .and_then(|id| self.uncertain_turns.get(id))
        {
            self.status.push_str(if turn.admitted{" · Message delivered; response incomplete. /pending refreshes, /copy-pending copies."}else{" · Delivery uncertain. /pending checks the chat; /copy-pending copies. Do not resend blindly."});
        }
    }
    pub fn set_error(&mut self, error: &str) {
        self.hide_cached_chat();
        self.restore_pending_send();
        self.set_status(error);
        if let Some(form) = self.form.as_mut() {
            form.error = markdown::clean(error);
            form.busy = false;
        }
    }
    pub fn set_authenticated(&mut self, value: bool) {
        if self.authenticated && !value {
            self.clear_private();
            self.login_form();
        } else if !value && self.form.is_none() {
            self.login_form();
        }
        self.authenticated = value;
        if value
            && self.form.as_ref().is_some_and(|f| {
                matches!(
                    f.purpose,
                    FormPurpose::Login
                        | FormPurpose::Unlock
                        | FormPurpose::PairPin
                        | FormPurpose::Pairing
                )
            })
        {
            self.form = None;
        }
    }
    pub fn set_username(&mut self, value: &str) {
        self.username = markdown::clean(value);
    }
    /// Cached name for the first paint; never replaces an authenticated one.
    pub fn set_inspirations(&mut self, list: Vec<openmates_sdk::client::overview::inspirations::Inspiration>) {
        self.inspirations = list;
        self.inspiration_index = 0;
    }
    pub fn set_username_hint(&mut self, value: &str) {
        if self.username.is_empty() {
            self.username = markdown::clean(value);
        }
    }
    pub fn set_unlock_required(&mut self, value: bool) {
        if value {
            self.form = Some(Form::new(
                "Unlock local vault",
                FormPurpose::Unlock,
                vec![Field::secret("passphrase", "Vault passphrase")],
            ));
        }
    }
    pub fn set_pair_pin_required(&mut self) {
        let mut vault = Field::secret(
            "vault_passphrase",
            "Local vault passphrase (if OS keyring unavailable)",
        );
        vault.required = false;
        self.form = Some(Form::new(
            "Pairing PIN",
            FormPurpose::PairPin,
            vec![Field::secret("pin", "PIN from your browser"), vault],
        ));
    }
    pub fn set_share_url(&mut self, uri: &str) {
        self.form = Some(Form::new(
            "Private share link · only share with intended recipients",
            FormPurpose::ShareResult {
                visible: false,
                qr: false,
            },
            vec![Field::multiline("link", "Share URL", uri)],
        ));
    }
    pub fn set_pairing(&mut self, uri: &str) {
        self.form = Some(Form::new(
            "Pair this terminal",
            FormPurpose::Pairing,
            vec![Field::text(
                "uri",
                "Open this address in your signed-in browser",
                uri,
                false,
            )],
        ));
    }
    pub fn is_selecting_text(&self) -> bool {
        self.selecting
    }
    pub fn resize(&mut self, width: u16, height: u16) {
        self.size = (width, height);
        self.hits.clear();
        self.composer_rect = Rect::default();
    }
    /// Consume delivery fences for an operation whose visible view has changed.
    /// These updates settle its original send without painting content into another chat.
    pub fn background_stream(&mut self, update: StreamUpdate) {
        match update {
            StreamUpdate::Started {
                chat_id,
                message_id,
                expects_reply,
            } => {
                if self
                    .pending_send
                    .as_ref()
                    .is_none_or(|(key, _)| key != &chat_id && key != "__new__")
                {
                    return;
                }
                if let Some((key, _)) = self.pending_send.as_mut()
                    && key == "__new__"
                {
                    *key = chat_id.clone();
                    if let Some(draft) = self.drafts.remove("__new__") {
                        self.drafts.insert(chat_id.clone(), draft);
                    }
                }
                if self
                    .active_turn
                    .as_ref()
                    .is_none_or(|turn| turn.chat_id != chat_id || turn.user_id != message_id)
                {
                    self.active_turn = Some(ActiveTurn {
                        chat_id,
                        user_id: message_id,
                        assistant: None,
                        expects_reply,
                    });
                }
            }
            StreamUpdate::Submitted {
                chat_id,
                message_id,
            } => {
                if self
                    .pending_send
                    .as_ref()
                    .is_some_and(|(key, _)| key == &chat_id || key == "__new__")
                {
                    self.delivery = Delivery::Submitted {
                        chat_id: chat_id.clone(),
                        message_id,
                    };
                    self.drafts.remove(&format!("__retry__:{chat_id}"));
                }
            }
            StreamUpdate::Admitted {
                chat_id,
                message_id,
            } => {
                if matches!(&self.delivery,Delivery::Submitted{chat_id:id,message_id:message}if id==&chat_id&&message==&message_id)
                {
                    self.delivery = Delivery::Admitted {
                        chat_id,
                        message_id,
                    };
                }
            }
            StreamUpdate::Completed {
                chat_id,
                message_id,
                content,
            } => {
                let matches = self.active_turn.as_ref().is_some_and(|turn| {
                    turn.chat_id == chat_id
                        && ((message_id == turn.user_id && content.is_empty())
                            || (message_id != turn.user_id && turn.expects_reply))
                });
                if matches
                    && self
                        .pending_send
                        .as_ref()
                        .is_some_and(|(key, _)| key == &chat_id)
                {
                    self.send_succeeded();
                }
            }
            StreamUpdate::Consent { request_id, items } => {
                let context = self
                    .active_turn
                    .as_ref()
                    .and_then(|turn| self.items[0].iter().find(|item| item.id == turn.chat_id))
                    .map(|item| item.title.clone())
                    .unwrap_or_else(|| "Background chat".into());
                self.stream(StreamUpdate::Consent { request_id, items });
                if let Some(form) = self.form.as_mut() {
                    form.context = Some(context);
                }
            }
            StreamUpdate::Content { .. } | StreamUpdate::Status(_) => {}
        }
    }
    pub fn stream(&mut self, update: StreamUpdate) {
        self.chat_layout = None;
        match update {
            StreamUpdate::Started {
                chat_id,
                message_id,
                expects_reply,
            } => {
                if self.chat.as_ref().is_none_or(|c| c.id != chat_id) {
                    self.remember_draft();
                    let migrate = self
                        .pending_send
                        .as_ref()
                        .is_some_and(|(key, _)| key == "__new__");
                    if migrate {
                        if let Some((key, _)) = self.pending_send.as_mut() {
                            *key = chat_id.clone();
                        }
                        if let Some(draft) = self.drafts.remove("__new__") {
                            self.drafts.insert(chat_id.clone(), draft);
                        }
                    }
                    self.chat = Some(Chat {
                        id: chat_id,
                        title: "New chat".into(),
                        ..Default::default()
                    });
                    self.restore_draft();
                }
                let chat = self.chat.as_mut().unwrap();
                if !chat.messages.iter().any(|message| message.id == message_id)
                    && let Some((key, text)) = &self.pending_send
                    && key == &chat.id
                {
                    chat.messages.push(Message {
                        id: message_id.clone(),
                        role: "user".into(),
                        content: text.to_string(),
                        ..Default::default()
                    });
                }
                if self
                    .active_turn
                    .as_ref()
                    .is_none_or(|turn| turn.chat_id != chat.id || turn.user_id != message_id)
                {
                    self.active_turn = Some(ActiveTurn {
                        chat_id: chat.id.clone(),
                        user_id: message_id,
                        assistant: None,
                        expects_reply,
                    });
                }
                self.workspace = Workspace::Chats;
                self.detail = None;
                self.streaming = expects_reply;
            }
            StreamUpdate::Submitted {
                chat_id,
                message_id,
            } => {
                if self
                    .pending_send
                    .as_ref()
                    .is_some_and(|(key, _)| key == &chat_id || key == "__new__")
                {
                    self.delivery = Delivery::Submitted {
                        chat_id: chat_id.clone(),
                        message_id,
                    };
                    self.drafts.remove(&format!("__retry__:{chat_id}"));
                }
            }
            StreamUpdate::Admitted {
                chat_id,
                message_id,
            } => {
                if matches!(&self.delivery,Delivery::Submitted{chat_id:id,message_id:message}if id==&chat_id&&message==&message_id)
                {
                    self.delivery = Delivery::Admitted {
                        chat_id,
                        message_id,
                    };
                }
            }
            StreamUpdate::Content {
                content,
                thinking,
                mate,
            } => {
                if let Some(turn) = self.active_turn.as_mut().filter(|turn| turn.expects_reply)
                    && let Some(chat) = self.chat.as_mut().filter(|chat| chat.id == turn.chat_id)
                {
                    let id = turn
                        .assistant
                        .get_or_insert_with(|| format!("__pending_assistant__:{}", turn.user_id));
                    if !chat
                        .messages
                        .iter()
                        .any(|message| message.id == *id && message.role == "assistant")
                    {
                        chat.messages.push(Message {
                            id: id.clone(),
                            role: "assistant".into(),
                            ..Default::default()
                        });
                    }
                    if let Some(message) = chat
                        .messages
                        .iter_mut()
                        .find(|message| message.id == *id && message.role == "assistant")
                    {
                        message.content = content;
                        message.thinking = thinking;
                        if !mate.is_empty() {
                            message.sender = mate;
                        }
                    }
                }
            }
            StreamUpdate::Completed {
                chat_id,
                message_id,
                content,
            } => {
                let mut completed = false;
                if let Some(turn) = self
                    .active_turn
                    .as_ref()
                    .filter(|turn| turn.chat_id == chat_id)
                    && let Some(chat) = self.chat.as_mut().filter(|chat| chat.id == chat_id)
                {
                    if message_id == turn.user_id {
                        if content.is_empty() {
                            if let Some(id) = &turn.assistant {
                                chat.messages.retain(|message| {
                                    message.id != *id
                                        || !message.content.is_empty()
                                        || !message.thinking.is_empty()
                                });
                            }
                            completed = true;
                            self.status = "Message delivered".into();
                        }
                    } else if turn.expects_reply {
                        if let Some(existing) = chat
                            .messages
                            .iter_mut()
                            .find(|message| message.id == message_id && message.role == "assistant")
                        {
                            existing.content = content;
                        } else if let Some(placeholder) = turn.assistant.as_ref().and_then(|id| {
                            chat.messages
                                .iter_mut()
                                .find(|message| message.id == *id && message.role == "assistant")
                        }) {
                            placeholder.id = message_id;
                            placeholder.content = content;
                        } else {
                            chat.messages.push(Message {
                                id: message_id,
                                role: "assistant".into(),
                                content,
                                ..Default::default()
                            });
                        }
                        completed = true;
                        self.status = "Response complete".into();
                    }
                }
                if completed {
                    self.send_succeeded();
                }
            }
            StreamUpdate::Consent { request_id, items } => {
                let fields = items
                    .iter()
                    .map(|item| {
                        let mut field = Field::text(
                            &item.id,
                            &format!("{} · {}", item.title, item.description),
                            "false",
                            false,
                        );
                        field.kind = FieldKind::Bool;
                        field
                    })
                    .collect();
                let title = if items
                    .iter()
                    .any(|item| item.fields["consent_kind"] == "sub_chats")
                {
                    "Start these sub-chats? · nothing starts until you approve"
                } else {
                    "Review requested Memories · nothing is shared until you approve"
                };
                self.form = Some(Form::new(
                    title,
                    FormPurpose::Consent { request_id, items },
                    fields,
                ));
                self.hits.clear();
            }
            StreamUpdate::Status(status) => self.set_status(&status),
        }
    }
    fn selected_item(&self) -> Option<&Item> {
        self.items[index(self.workspace)].get(self.selected[index(self.workspace)])
    }
    fn hit(&mut self, rect: Rect, action: HitAction) {
        if rect.width > 0 && rect.height > 0 {
            self.hits.push(Hit { rect, action });
        }
    }
    fn nav(&mut self, workspace: Workspace) -> Vec<UiCommand> {
        if workspace == Workspace::Settings {
            return self.settings_toggle();
        }
        self.remember_draft();
        self.workspace = workspace;
        self.chat = None;
        self.cached_chat_state = None;
        self.restore_draft();
        self.detail = None;
        self.origin = None;
        self.chat_origin = None;
        self.app_history.clear();
        self.detail_tab = 0;
        self.scroll = 0;
        self.focus = Focus::Content;
        self.hits.clear();
        vec![UiCommand::Refresh(workspace)]
    }
    fn settings_toggle(&mut self) -> Vec<UiCommand> {
        // All entry points (shortcuts, palette and pointer) share this origin
        // normalization. A transient navigation selector cannot own Settings.
        if self.focus == Focus::Navigation {
            self.focus = self.navigation_return;
        }
        if let Some(settings) = self.settings.take() {
            self.sidebar = settings.sidebar_before;
            self.focus = settings.focus_before;
            self.scroll = settings.scroll_before;
        } else {
            self.settings = Some(Settings {
                route: String::new(),
                selected: 0,
                sidebar_before: self.sidebar,
                focus_before: self.focus,
                scroll_before: self.scroll,
            });
            self.sidebar = false;
            self.focus = Focus::Content;
        }
        self.hits.clear();
        vec![UiCommand::Refresh(Workspace::Settings)]
    }
    fn open_selected(&mut self, selected: usize) -> Vec<UiCommand> {
        let Some(item) = self.items[index(self.workspace)].get(selected).cloned() else {
            return vec![];
        };
        self.selected[index(self.workspace)] = selected;
        if self.workspace == Workspace::Chats && item.id.starts_with("embed:") {
            // A due-soon saved item of the home carousel, like `/embed <id>`.
            return vec![UiCommand::Open(Workspace::Apps, item.id)];
        }
        if self.workspace != Workspace::Chats {
            self.detail = Some(item.clone());
            self.detail_tab = 0;
            self.scroll = 0;
            self.focus = Focus::Content;
        }
        vec![UiCommand::Open(self.workspace, item.id)]
    }
    fn back(&mut self) -> Vec<UiCommand> {
        if self.form.take().is_some() {
            self.hits.clear();
            return vec![];
        }
        if let Some(settings) = self.settings.as_mut() {
            if settings.route.is_empty() {
                return self.settings_toggle();
            }
            settings.route = settings
                .route
                .rsplit_once('/')
                .map(|(p, _)| p.to_owned())
                .unwrap_or_default();
            settings.selected = 0;
            self.hits.clear();
            return vec![];
        }
        self.remember_draft();
        if self.workspace == Workspace::Apps
            && let Some((item, tab)) = self.app_history.pop()
        {
            self.detail = Some(item);
            self.detail_tab = tab;
            self.scroll = 0;
            self.hits.clear();
            return vec![];
        }
        if let Some((chat, scroll, follow, cached)) = self.chat_origin.take() {
            self.workspace = Workspace::Chats;
            self.chat = Some(chat);
            self.cached_chat_state = cached;
            self.restore_draft();
            self.detail = None;
            self.scroll = scroll;
            self.follow_tail = follow;
            self.chat_layout = None;
            self.hits.clear();
            return vec![];
        }
        if let Some((workspace, item, tab)) = self.origin.take() {
            self.workspace = workspace;
            self.detail = Some(item);
            self.detail_tab = tab;
            self.chat = None;
            self.cached_chat_state = None;
        } else if self.chat.take().is_some() || self.detail.take().is_some() {
            self.cached_chat_state = None;
            self.focus = Focus::Content;
        } else if self.sidebar {
            self.sidebar = false;
            self.focus = Focus::Composer;
        }
        self.restore_draft();
        self.scroll = 0;
        self.hits.clear();
        vec![]
    }
    pub fn key(&mut self, event: KeyEvent) -> Vec<UiCommand> {
        if event.kind == KeyEventKind::Release {
            return vec![];
        }
        let ctrl = event.modifiers.contains(KeyModifiers::CONTROL);
        if ctrl {
            match event.code {
                KeyCode::Char('c') => {
                    if self.streaming || self.pending_send.is_some() {
                        return vec![UiCommand::Cancel];
                    }
                    return vec![UiCommand::Quit];
                }
                KeyCode::Char('q') => return vec![UiCommand::Quit],
                KeyCode::Char('o') if !self.inspirations.is_empty() => {
                    self.inspiration_index = (self.inspiration_index + 1) % self.inspirations.len();
                    return vec![];
                }
                KeyCode::Char('y') => {
                    self.selecting = !self.selecting;
                    self.hits.clear();
                    self.status = if self.selecting {
                        "Text selection enabled · Ctrl+Y returns to pointer mode"
                    } else {
                        "Pointer mode enabled"
                    }
                    .into();
                    return vec![UiCommand::SelectionMode(self.selecting)];
                }
                _ => {}
            }
        }
        if self.form.is_some() {
            return self.form_key(event);
        }
        // Modal forms keep their existing ownership above this shortcut.
        if ctrl && event.code == KeyCode::Char('g') {
            if self.focus != Focus::Navigation {
                self.navigation_return = self.focus;
            }
            self.navigation_index = if self.settings.is_some() { 5 } else { index(self.workspace) };
            self.focus = Focus::Navigation;
            self.hits.clear();
            return vec![];
        }
        if event.code == KeyCode::Esc && self.focus != Focus::Navigation {
            return self.back();
        }
        if ctrl {
            match event.code {
                KeyCode::Char('b') => {
                    self.sidebar = !self.sidebar;
                    self.focus = if self.sidebar {
                        Focus::Sidebar
                    } else {
                        Focus::Composer
                    };
                    self.hits.clear();
                    return vec![];
                }
                KeyCode::Char('k' | 'p') => {
                    self.palette_query.clear();
                    self.form = Some(Form::new("Actions", FormPurpose::Palette, vec![]));
                    return vec![];
                }
                KeyCode::Char('n') => {
                    self.new_chat();
                    return vec![];
                }
                KeyCode::Char('r') => {
                    return vec![UiCommand::Refresh(if self.settings.is_some() {
                        Workspace::Settings
                    } else {
                        self.workspace
                    })];
                }
                KeyCode::Char('s') => return self.settings_toggle(),
                KeyCode::Char('l') => {
                    self.login_form();
                    return vec![];
                }
                KeyCode::Char(c @ '1'..='6') => {
                    return self.nav(Workspace::ALL[(c as u8 - b'1') as usize]);
                }
                _ => {}
            }
        }
        // TS parity (tuiWorkspaceController): `/` on an empty draft starts a
        // command from any focus, and typing on the chat home starts a draft
        // instead of triggering card shortcuts; Enter still opens the card.
        let plain_char = matches!(event.code, KeyCode::Char(_))
            && !event.modifiers.intersects(KeyModifiers::CONTROL | KeyModifiers::ALT);
        if plain_char && self.settings.is_none() && self.focus != Focus::Composer {
            let slash = event.code == KeyCode::Char('/') && self.draft.text.is_empty();
            let chat_home = self.focus == Focus::Content
                && self.workspace == Workspace::Chats
                && self.chat.is_none()
                && self.detail.is_none();
            if slash || chat_home {
                self.focus = Focus::Composer;
                self.hits.clear();
                self.draft.key(event);
                return vec![];
            }
        }
        if self.focus == Focus::Navigation {
            match event.code {
                KeyCode::Left => self.navigation_index = (self.navigation_index + 5) % 6,
                KeyCode::Right => self.navigation_index = (self.navigation_index + 1) % 6,
                KeyCode::Enter => {
                    // Restore the originating owner before invoking existing operations:
                    // settings must remember that owner, never Navigation.
                    self.focus = self.navigation_return;
                    let workspace = Workspace::ALL[self.navigation_index];
                    if workspace != Workspace::Settings && self.settings.is_some() {
                        let _ = self.settings_toggle();
                    }
                    return self.nav(workspace);
                }
                KeyCode::Esc | KeyCode::Tab | KeyCode::BackTab => {
                    self.focus = self.navigation_return;
                    self.hits.clear();
                }
                _ => {}
            }
            return vec![];
        }
        let backwards_tab = event.code == KeyCode::BackTab
            || (event.code == KeyCode::Tab && event.modifiers.contains(KeyModifiers::SHIFT));
        if self.settings.is_some() && self.size.0 < 120 {
            if matches!(event.code, KeyCode::Tab | KeyCode::BackTab) {
                self.focus = Focus::Content;
                return self.settings_key(KeyEvent::new(
                    if backwards_tab {
                        KeyCode::Up
                    } else {
                        KeyCode::Down
                    },
                    KeyModifiers::NONE,
                ));
            }
            if !ctrl {
                self.focus = Focus::Content;
                return self.settings_key(event);
            }
        }
        if self.focus == Focus::Sidebar
            && self.settings.is_none()
            && matches!(event.code, KeyCode::Home | KeyCode::End | KeyCode::PageUp | KeyCode::PageDown)
        {
            let i = index(Workspace::Chats);
            let last = self.items[i].len().saturating_sub(1);
            let step = self.size.1.saturating_sub(9).max(1) as usize;
            self.selected[i] = match event.code {
                KeyCode::Home => 0,
                KeyCode::End => last,
                KeyCode::PageUp => self.selected[i].saturating_sub(step).min(last),
                KeyCode::PageDown => self.selected[i].saturating_add(step).min(last),
                _ => unreachable!(),
            };
            return vec![];
        }
        match event.code {
            KeyCode::F(1) => {
                self.form = Some(Form::new("Keyboard shortcuts", FormPurpose::Help, vec![]));
                return vec![];
            }
            KeyCode::Tab | KeyCode::BackTab => {
                self.focus = match (self.focus, backwards_tab) {
                    (Focus::Composer, true) => Focus::Content,
                    (Focus::Content, true) if self.sidebar => Focus::Sidebar,
                    (Focus::Content, true) => Focus::Composer,
                    (Focus::Sidebar, true) => Focus::Composer,
                    (Focus::Composer, false) if self.sidebar => Focus::Sidebar,
                    (Focus::Composer, false) => Focus::Content,
                    (Focus::Sidebar, false) => Focus::Content,
                    (Focus::Content, false) => Focus::Composer,
                    (Focus::Navigation, _) => unreachable!("navigation keys handled above"),
                };
                return vec![];
            }
            KeyCode::PageUp => {
                self.scroll = self
                    .scroll
                    .saturating_sub(self.size.1.saturating_sub(8) as usize);
                self.follow_tail = false;
                return vec![];
            }
            KeyCode::PageDown => {
                self.scroll = self
                    .scroll
                    .saturating_add(self.size.1.saturating_sub(8) as usize);
                self.follow_tail = false;
                return vec![];
            }
            _ => {}
        }
        if self.settings.is_some() && self.focus != Focus::Composer {
            return self.settings_key(event);
        }
        if self.focus == Focus::Composer {
            if event.code == KeyCode::Enter {
                if event
                    .modifiers
                    .intersects(KeyModifiers::ALT | KeyModifiers::SHIFT)
                {
                    self.draft.insert("\n");
                    return vec![];
                }
                return self.send();
            }
            self.draft.key(event);
            return vec![];
        }
        if self.focus == Focus::Sidebar {
            let i = index(Workspace::Chats);
            match event.code {
                KeyCode::Up => self.selected[i] = self.selected[i].saturating_sub(1),
                KeyCode::Down => {
                    self.selected[i] =
                        (self.selected[i] + 1).min(self.items[i].len().saturating_sub(1))
                }
                KeyCode::Enter => {
                    let n = self.selected[i];
                    self.workspace = Workspace::Chats;
                    return self.open_selected(n);
                }
                _ => {}
            }
            return vec![];
        }
        if self.chat.is_some() {
            let links = self.content_links();
            match event.code {
                KeyCode::Left => self.content_action = self.content_action.saturating_sub(1),
                KeyCode::Right => {
                    self.content_action =
                        (self.content_action + 1).min(links.len().saturating_sub(1))
                }
                KeyCode::Up => {
                    self.scroll = self.scroll.saturating_sub(1);
                    self.follow_tail = false;
                }
                KeyCode::Down => {
                    self.scroll = self.scroll.saturating_add(1);
                    self.follow_tail = false;
                }
                KeyCode::Enter => {
                    if let Some(link) = links.get(self.content_action) {
                        return self.activate(HitAction::Link(link.clone()));
                    }
                }
                KeyCode::Char('q') => {
                    if let Some(link) = links
                        .into_iter()
                        .find(|link| matches!(link, Link::Question(_)))
                    {
                        return self.activate(HitAction::Link(link));
                    }
                }
                _ => {}
            }
            return vec![];
        }
        if self.detail.is_some() {
            if event.code == KeyCode::Enter
                && let Some(item) = self.detail.as_ref()
            {
                if self.workspace == Workspace::Apps && item.fields.get("input_schema").is_some() {
                    self.app_input_form();
                    return vec![];
                }
                let link = match (self.workspace, self.detail_tab) {
                    (Workspace::Apps, 1) => field_list(item, "skills")
                        .get(self.node_selected)
                        .and_then(|skill| {
                            let id = skill["id"].as_str().or_else(|| skill.as_str())?;
                            Some(Link::Skill {
                                app: item.id.clone(),
                                skill: id.into(),
                            })
                        }),
                    (Workspace::Workflows, 0) => Some(Link::Node(self.node_selected)),
                    (Workspace::Workflows, 1) => field_list(item, "runs")
                        .get(self.node_selected)
                        .cloned()
                        .map(Link::Run),
                    (Workspace::Projects, 1) => field_list(item, "files")
                        .get(self.node_selected)
                        .and_then(|file| {
                            let embed = file
                                .get("embedId")
                                .or_else(|| file.get("embed_id"))
                                .or_else(|| file.get("target_id"))
                                .and_then(Value::as_str)
                                .unwrap_or("");
                            if embed.is_empty() {
                                None
                            } else {
                                Some(Link::ProjectFile {
                                    project: item.id.clone(),
                                    embed: embed.into(),
                                    name: text_field(file, "name").into(),
                                })
                            }
                        }),
                    _ => self.detail_links.get(self.node_selected).cloned(),
                };
                if let Some(link) = link {
                    return self.activate(HitAction::Link(link));
                }
            }
            match event.code {
                KeyCode::Char('e') if self.workspace != Workspace::Apps => {
                    self.edit_form(false);
                    return vec![];
                }
                KeyCode::Char('d') if self.workspace != Workspace::Apps => {
                    self.delete_form();
                    return vec![];
                }
                KeyCode::Char('r') if self.workspace == Workspace::Workflows => {
                    return self.activate(HitAction::Run);
                }
                KeyCode::Char('t') if self.workspace == Workspace::Workflows => {
                    return self.activate(HitAction::Toggle);
                }
                KeyCode::Char('1'..='3') => {
                    if let KeyCode::Char(c) = event.code {
                        self.detail_tab = (c as u8 - b'1') as usize;
                        self.scroll = 0;
                    }
                    return vec![];
                }
                KeyCode::Down if self.workspace == Workspace::Apps => {
                    let count = if self.detail_tab == 1 {
                        self.detail
                            .as_ref()
                            .map(|item| field_list(item, "skills").len())
                            .unwrap_or(0)
                    } else {
                        self.detail_links.len()
                    };
                    self.node_selected = (self.node_selected + 1).min(count.saturating_sub(1));
                    self.scroll = self.scroll.saturating_add(1);
                    self.follow_tail = false;
                }
                KeyCode::Down => {
                    self.node_selected = self.node_selected.saturating_add(1).min(
                        self.detail
                            .as_ref()
                            .and_then(|i| {
                                i.fields
                                    .get("nodes")
                                    .or_else(|| i.fields.pointer("/graph/nodes"))
                            })
                            .and_then(Value::as_array)
                            .map(|n| n.len().saturating_sub(1))
                            .unwrap_or(0),
                    );
                    self.scroll = self.scroll.saturating_add(1);
                    self.follow_tail = false;
                }
                KeyCode::Up => {
                    self.node_selected = self.node_selected.saturating_sub(1);
                    self.scroll = self.scroll.saturating_sub(1);
                    self.follow_tail = false;
                }
                _ => {}
            }
            return vec![];
        }
        match event.code {
            KeyCode::Left | KeyCode::Up => {
                let i = index(self.workspace);
                self.selected[i] = self.selected[i].saturating_sub(1);
            }
            KeyCode::Right | KeyCode::Down => {
                let i = index(self.workspace);
                self.selected[i] =
                    (self.selected[i] + 1).min(self.items[i].len().saturating_sub(1));
            }
            KeyCode::Enter => return self.open_selected(self.selected[index(self.workspace)]),
            KeyCode::Char('n') => self.edit_form(true),
            KeyCode::Char('e') => self.edit_form(false),
            KeyCode::Char('d') => self.delete_form(),
            KeyCode::Char('s') if self.workspace == Workspace::Tasks => {
                if let Some(item) = self.selected_item() {
                    let id = item.id.clone();
                    let status = task_next(&item.status).to_owned();
                    return vec![UiCommand::Mutate(Mutation::Update {
                        workspace: Workspace::Tasks,
                        id,
                        fields: json!({"status":status}),
                    })];
                }
            }
            _ => {}
        }
        vec![]
    }
    pub fn paste(&mut self, text: &str) -> Vec<UiCommand> {
        if let Some(form) = self.form.as_mut() {
            if matches!(form.purpose, FormPurpose::Palette) {
                self.palette_query.insert(text);
            } else if !form.busy
                && let Some(field) = form.fields.get_mut(form.selected)
                && matches!(
                    field.kind,
                    FieldKind::Text | FieldKind::Secret | FieldKind::Number | FieldKind::Multiline
                )
            {
                field.editor.insert(text);
            }
        } else if self.focus == Focus::Composer {
            self.draft.insert(text);
        } else if self.focus == Focus::Content
            && self.workspace == Workspace::Chats
            && self.chat.is_none()
            && self.detail.is_none()
            && self.settings.is_none()
        {
            // TS parity: pasting on the chat home starts a draft like typing.
            self.focus = Focus::Composer;
            self.hits.clear();
            self.draft.insert(text);
        }
        vec![]
    }
    pub fn mouse(&mut self, event: MouseEvent) -> Vec<UiCommand> {
        if self.selecting || !event.modifiers.is_empty() {
            return vec![];
        }
        match event.kind {
            MouseEventKind::ScrollUp => {
                if let Some(form) = self.form.as_mut() {
                    if matches!(
                        form.purpose,
                        FormPurpose::Help | FormPurpose::AppConfirm { .. }
                    ) {
                        form.scroll = form.scroll.saturating_sub(3);
                    }
                } else {
                    self.scroll = self.scroll.saturating_sub(3);
                    self.follow_tail = false;
                }
                vec![]
            }
            MouseEventKind::ScrollDown => {
                if let Some(form) = self.form.as_mut() {
                    if matches!(
                        form.purpose,
                        FormPurpose::Help | FormPurpose::AppConfirm { .. }
                    ) {
                        form.scroll = form.scroll.saturating_add(3);
                    }
                } else {
                    self.scroll = self.scroll.saturating_add(3);
                    self.follow_tail = false;
                }
                vec![]
            }
            MouseEventKind::Down(MouseButton::Left) => {
                let action = self
                    .hits
                    .iter()
                    .rev()
                    .find(|hit| hit.rect.contains((event.column, event.row).into()))
                    .map(|h| h.action.clone());
                if let Some(HitAction::Composer) = action {
                    self.draft.click(
                        self.composer_rect.width as usize,
                        event.column.saturating_sub(self.composer_rect.x) as usize,
                        event.row.saturating_sub(self.composer_rect.y) as usize
                            + self.composer_offset,
                    );
                }
                action.map(|a| self.activate(a)).unwrap_or_default()
            }
            _ => vec![],
        }
    }
    fn activate(&mut self, action: HitAction) -> Vec<UiCommand> {
        if matches!(&action, HitAction::Copy | HitAction::Edit | HitAction::Delete | HitAction::Run | HitAction::Toggle)
            && self.cached_action_blocked() { return vec![]; }
        match action {
            HitAction::SkillRun=>{self.app_input_form();vec![]},
            HitAction::DenyConsent=>{if let Some(form)=self.form.take()&& let FormPurpose::Consent{request_id,..}=form.purpose{return vec![UiCommand::Consent{request_id,approved_ids:vec![]}];}vec![]},
            HitAction::RevealShare=>{if let Some(form)=self.form.as_mut()&& let FormPurpose::ShareResult{visible,qr}= &mut form.purpose{*visible = !*visible;*qr=false;}vec![]},
            HitAction::QrShare=>{if let Some(form)=self.form.as_mut()&& let FormPurpose::ShareResult{qr,..}= &mut form.purpose{*qr = !*qr;}vec![]},
            HitAction::CopyShare=>self.form.as_ref().and_then(|f|f.fields.first()).map(|f|vec![UiCommand::Copy(f.editor.text.to_string())]).unwrap_or_default(),
            HitAction::Nav(w)=>self.nav(w),HitAction::Settings=>self.settings_toggle(),
            HitAction::Sidebar=>{self.sidebar = !self.sidebar;self.hits.clear();vec![]},
            HitAction::NewChat=>{self.new_chat();vec![]},
            HitAction::Open(i)=>self.open_selected(i),
            HitAction::SidebarItem(i)=>{self.workspace=Workspace::Chats;self.open_selected(i)},
            HitAction::Composer=>{self.focus=Focus::Composer;vec![]},
            HitAction::Back=>self.back(),HitAction::Close=>{if self.settings.is_some(){self.settings_toggle()}else{self.back()}},
            HitAction::DetailTab(i)=>{self.detail_tab=i;self.scroll=0;vec![]},
            HitAction::Edit=>{self.edit_form(false);vec![]},HitAction::Create=>{self.edit_form(true);vec![]},HitAction::Delete=>{self.delete_form();vec![]},
            HitAction::Run=>self.detail.as_ref().map(|i|vec![UiCommand::Mutate(Mutation::RunWorkflow{id:i.id.clone()})]).unwrap_or_default(),
            HitAction::Toggle=>self.detail.as_ref().map(|i|vec![UiCommand::Mutate(Mutation::Update{workspace:Workspace::Workflows,id:i.id.clone(),fields:json!({"enabled":!i.fields.get("enabled").and_then(Value::as_bool).unwrap_or(false)})})]).unwrap_or_default(),
            HitAction::Copy=>{let content=if let Some(chat)=&self.chat{chat.messages.iter().map(|m|format!("{}: {}",m.sender_or_role(),m.content)).collect::<Vec<_>>().join("\n\n")}else{self.detail.as_ref().map(|i|format!("{}\n\n{}",i.title,i.description)).unwrap_or_default()};vec![UiCommand::Copy(content)]},
            HitAction::Link(link)=>match link {Link::Skill{app,skill}=>vec![UiCommand::Open(Workspace::Apps,format!("skill:{app}/{skill}"))],
                Link::Node(i)=>{self.node_selected=i;self.edit_form(false);vec![]},
                Link::Run(run)=>{let title=format!("Run {}",text_field(&run,"id"));let content=display_value(&run);self.form=Some(Form::new(&title,FormPurpose::Help,vec![Field::multiline("content","Details",&content)]));vec![]},
                Link::ProjectFile{project,embed,name}=>{self.download_file_form(&project,&embed,&name);vec![]},
                Link::Carousel{message,delta}=>{let length=self.chat.as_ref().and_then(|c|c.messages.iter().find(|m|m.id==message)).map(|m|m.embeds.len()).unwrap_or(0);let offset=self.embed_offsets.entry(message).or_default();*offset=(*offset as i32+delta).max(0).min(length.saturating_sub(1)as i32)as usize;self.chat_layout=None;self.hits.clear();vec![]},
                Link::Url(url)=>vec![UiCommand::OpenUrl(url)],Link::Wiki(id)=>vec![UiCommand::Open(Workspace::Apps,format!("wiki:{id}"))],Link::Embed(id)=>vec![UiCommand::Open(Workspace::Apps,format!("embed:{id}"))],Link::Question(value)=>{self.question_form(value);vec![]}},

            HitAction::FormField(i)=>{if let Some(form)=self.form.as_mut(){form.selected=i;self.cycle_field(1);}vec![]},
            HitAction::FormSubmit=>{if self.form.as_ref().is_some_and(|f|matches!(f.purpose,FormPurpose::Pairing)){self.set_pair_pin_required();vec![]}else{self.submit_form()}},HitAction::FormCancel=>self.cancel_form(),
            HitAction::Palette(i)=>{let actions=self.palette_actions();if let Some((_,command))=actions.get(i){let command=command.to_string();self.form=None;self.command(&command)}else{vec![]}},
            HitAction::SettingsRoute(route)=>{if let Some(settings)=self.settings.as_mut(){settings.route=route.clone();settings.selected=0;self.focus=Focus::Content;}vec![UiCommand::Open(Workspace::Settings,route)]},
            HitAction::Login=>{self.login_form();vec![]},
            HitAction::Pair=>vec![UiCommand::BeginPair],HitAction::Logout=>vec![UiCommand::Logout],
            HitAction::NextCard(delta)=>{let i=index(self.workspace);self.selected[i]=(self.selected[i]as i32+delta).max(0).min(self.items[i].len().saturating_sub(1)as i32)as usize;vec![]},
            HitAction::SettingsEdit=>{self.settings_form();vec![]},
            HitAction::Share=>{self.share_form();vec![]},HitAction::Download=>{self.download_form();vec![]},
        }
    }
    fn send(&mut self) -> Vec<UiCommand> {
        if self.draft.text.trim().is_empty() {
            return vec![];
        }
        if self.draft.text.starts_with('/') {
            let command = self.draft.text.to_string();
            self.draft.clear();
            return self.command(&command);
        }
        if !self.authenticated {
            self.login_form();
            return vec![];
        }
        if self.cached_action_blocked() { return vec![]; }
        if self.uncertain_turns.contains_key(&self.draft_key()) {
            self.set_status("Refresh this chat to check its previous message before sending again");
            return vec![];
        }
        if self.streaming || self.pending_send.is_some() {
            self.status = "Response in progress · Ctrl+C stops it".into();
            return vec![];
        }
        let key = self.draft_key();
        let text = self.draft.take().to_string();
        self.drafts.remove(&key);
        self.pending_send = Some((key, Zeroizing::new(text.clone())));
        self.delivery = Delivery::Staged;
        self.follow_tail = true;
        self.status = "Sending…".into();
        vec![UiCommand::Send {
            chat_id: self.chat.as_ref().map(|c| c.id.clone()),
            text,
        }]
    }
    fn command(&mut self, input: &str) -> Vec<UiCommand> {
        let (name, value) = input.trim().split_once(' ').unwrap_or((input.trim(), ""));
        match name {
            "/exit" | "/quit" => vec![UiCommand::Quit],
            "/pending" | "/copy-pending" => {
                let id = if !value.is_empty() {
                    Some(value.to_owned())
                } else if self.uncertain_turns.contains_key(&self.draft_key()) {
                    Some(self.draft_key())
                } else {
                    self.last_uncertain.clone()
                };
                if let Some(id) = id
                    && let Some(turn) = self.uncertain_turns.get(&id)
                {
                    return if name == "/copy-pending" {
                        vec![UiCommand::Copy(turn.text.to_string())]
                    } else {
                        vec![UiCommand::Open(Workspace::Chats, id)]
                    };
                }
                self.status = "No uncertain message is awaiting confirmation".into();
                vec![]
            }
            "/retry" => {
                if self.uncertain_turns.contains_key(&self.draft_key()) {
                    self.set_status(
                        "This message may already be delivered. Use /pending instead of retrying.",
                    );
                    return vec![];
                }
                if self.draft.text.is_empty() {
                    if let Some(text) = self.drafts.get(&format!("__retry__:{}", self.draft_key()))
                    {
                        self.draft = Editor::from(text);
                        self.focus = Focus::Composer;
                    } else {
                        self.status = "No failed message to retry in this chat".into();
                    }
                } else {
                    self.status="Your current draft is preserved. Clear or send it before restoring the failed message.".into();
                }
                vec![]
            }
            "/stop" => vec![UiCommand::Cancel],
            "/chats" | "/browse" => self.nav(Workspace::Chats),
            "/apps" => self.nav(Workspace::Apps),
            "/app-skill" if !value.is_empty() => {
                vec![UiCommand::Open(Workspace::Apps, format!("skill:{value}"))]
            }
            "/app-run" => {
                self.app_input_form();
                vec![]
            }
            "/projects" => self.nav(Workspace::Projects),
            "/workflows" => self.nav(Workspace::Workflows),
            "/tasks" => self.nav(Workspace::Tasks),
            "/share" => {
                self.share_form();
                vec![]
            }
            "/download" => {
                self.download_form();
                vec![]
            }
            "/team" => {
                self.form = Some(Form::new(
                    "Switch Team",
                    FormPurpose::Team,
                    vec![Field::text(
                        "team_id",
                        "Team ID (empty for personal workspace)",
                        "",
                        false,
                    )],
                ));
                vec![]
            }
            "/settings" => self.settings_toggle(),
            "/refresh" => vec![UiCommand::Refresh(self.workspace)],
            "/login" => {
                self.login_form();
                vec![]
            }
            "/unlock" => {
                self.set_unlock_required(true);
                vec![]
            }
            "/pair" => vec![UiCommand::BeginPair],
            "/logout" => vec![UiCommand::Logout],
            "/sidebar" => self.activate(HitAction::Sidebar),
            "/new" => self.activate(HitAction::NewChat),
            "/active" => match self.running_chat_id() {
                Some(id) => vec![UiCommand::Open(Workspace::Chats, id)],
                None => vec![],
            },
            "/help" => {
                self.form = Some(Form::new("Keyboard shortcuts", FormPurpose::Help, vec![]));
                vec![]
            }
            "/task-create" | "/project-create" | "/workflow-create" => {
                self.workspace = match name {
                    "/task-create" => Workspace::Tasks,
                    "/project-create" => Workspace::Projects,
                    _ => Workspace::Workflows,
                };
                self.edit_form(true);
                vec![]
            }
            "/task-edit" | "/workflow-edit" => {
                self.edit_form(false);
                vec![]
            }
            "/workflow-run" => self.activate(HitAction::Run),
            "/workflow-toggle" => self.activate(HitAction::Toggle),
            "/embed" | "/wiki" if !value.is_empty() => vec![UiCommand::Open(
                Workspace::Apps,
                format!("{}:{value}", &name[1..]),
            )],
            "/chat" | "/project" | "/task" | "/workflow" if !value.is_empty() => {
                let workspace = match name {
                    "/project" => Workspace::Projects,
                    "/task" => Workspace::Tasks,
                    "/workflow" => Workspace::Workflows,
                    _ => Workspace::Chats,
                };
                self.workspace = workspace;
                vec![UiCommand::Open(workspace, value.into())]
            }
            _ => {
                self.status = format!("Unknown action: {name} · Ctrl+K shows available actions");
                vec![]
            }
        }
    }
    fn share_form(&mut self) {
        if self.cached_action_blocked() { return; }
        let Some(chat) = &self.chat else {
            self.status = "Open a chat to configure sharing".into();
            return;
        };
        let expiry = Field::choice(
            "expires_in",
            "Link expires after",
            "1 day",
            vec![
                "1 minute",
                "1 hour",
                "1 day",
                "1 week",
                "2 weeks",
                "1 month",
                "3 months",
                "No expiration",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect(),
        );
        let mut password = Field::secret("password", "Link password (optional)");
        password.required = false;
        self.form = Some(Form::new(
            "Share chat · Generate Link explicitly shares this chat",
            FormPurpose::Share(chat.id.clone()),
            vec![expiry, password],
        ));
    }
    fn download_file_form(&mut self, project: &str, embed: &str, name: &str) {
        let mut overwrite =
            Field::text("overwrite", "Replace existing destination", "false", false);
        overwrite.kind = FieldKind::Bool;
        self.form = Some(Form::new(
            &format!("Download {name} · on this machine"),
            FormPurpose::Download(Workspace::Projects, format!("{project}/{embed}")),
            vec![
                Field::text("destination", "Local destination path", "", true),
                overwrite,
            ],
        ));
    }
    fn download_form(&mut self) {
        if self.cached_action_blocked() { return; }
        let Some((workspace, id)) = self
            .chat
            .as_ref()
            .map(|c| (Workspace::Chats, c.id.clone()))
            .or_else(|| self.detail.as_ref().map(|i| (self.workspace, i.id.clone())))
        else {
            self.status = "Open an item to download it".into();
            return;
        };
        let mut overwrite = Field::text(
            "overwrite",
            "Replace destination if it already exists",
            "false",
            false,
        );
        overwrite.kind = FieldKind::Bool;
        self.form = Some(Form::new(
            "Download · saved on the machine running this terminal",
            FormPurpose::Download(workspace, id),
            vec![
                Field::text("destination", "Local destination path", "", true),
                overwrite,
            ],
        ));
    }
    fn login_form(&mut self) {
        self.form = Some(Form::new(
            "Sign in to OpenMates",
            FormPurpose::Login,
            vec![
                Field::text("email", "Email", "", true),
                Field::secret("password", "Password"),
                {
                    let mut field = Field::secret("tfa", "Two-factor code (if enabled)");
                    field.required = false;
                    field
                },
            ],
        ));
    }
    fn app_input_form(&mut self) {
        let Some(skill) = self.detail.as_ref() else {
            self.status = "Open an app skill first".into();
            return;
        };
        if let Err(error) = apps::identifiers(skill) {
            self.status = error;
            return;
        }
        match apps::controls(skill) {
            Ok(fields) => {
                self.form = Some(Form::new(
                    &format!("Use {} · review before running", skill.title),
                    FormPurpose::AppInput(skill.clone()),
                    fields,
                ));
                self.hits.clear();
            }
            Err(error) => self.status = error,
        }
    }
    fn cancel_form(&mut self) -> Vec<UiCommand> {
        if let Some(form) = self.form.take() {
            match form.purpose {
                FormPurpose::AppConfirm { skill, draft, .. } => {
                    self.form = Some(Form::new(
                        &format!("Use {} · review before running", skill.title),
                        FormPurpose::AppInput(skill),
                        draft,
                    ));
                }
                FormPurpose::Consent { request_id, .. } => {
                    return vec![UiCommand::Consent {
                        request_id,
                        approved_ids: vec![],
                    }];
                }
                FormPurpose::Pairing | FormPurpose::PairPin => return vec![UiCommand::Cancel],
                _ => {}
            }
        }
        self.hits.clear();
        vec![]
    }
    fn edit_form(&mut self, create: bool) {
        let workspace = self.workspace;
        if matches!(
            workspace,
            Workspace::Chats | Workspace::Apps | Workspace::Settings
        ) {
            self.status = "Select a Project, Task or Workflow to edit".into();
            return;
        }
        let item = if create {
            None
        } else {
            self.detail.as_ref().or_else(|| self.selected_item())
        };
        if !create && item.is_none() {
            return;
        }
        let title = item.map(|i| i.title.as_str()).unwrap_or("");
        let description = item.map(|i| i.description.as_str()).unwrap_or("");
        let mut fields = vec![
            Field::text("title", "Title", title, true),
            Field::multiline("description", "Description", description),
        ];
        match workspace {
            Workspace::Tasks => {
                fields.push(Field::choice(
                    "status",
                    "Status",
                    item.map(|i| i.status.as_str())
                        .filter(|s| !s.is_empty())
                        .unwrap_or("todo"),
                    vec!["backlog", "todo", "in_progress", "blocked", "done"]
                        .into_iter()
                        .map(str::to_owned)
                        .collect(),
                ));
                fields.push(Field::choice(
                    "priority",
                    "Priority",
                    item.map(|i| match i.fields["priority"].as_u64() {
                        Some(0) => "none",
                        Some(1) => "low",
                        Some(2) => "medium",
                        Some(3) => "high",
                        Some(4) => "urgent",
                        _ => text_field(&i.fields, "priority"),
                    })
                    .filter(|s| !s.is_empty())
                    .unwrap_or("medium"),
                    vec!["none", "low", "medium", "high", "urgent"]
                        .into_iter()
                        .map(str::to_owned)
                        .collect(),
                ));
            }
            Workspace::Projects => {
                if create {
                    fields.push(Field::text(
                        "default_focus_id",
                        "Default focus ID",
                        "",
                        true,
                    ));
                    fields.push(Field::choice(
                        "write_mode",
                        "Write policy",
                        "always_ask",
                        vec!["always_ask".into(), "apply_and_show".into()],
                    ));
                } else {
                    for key in ["pinned", "archived"] {
                        let mut field = Field::text(
                            key,
                            if key == "pinned" {
                                "Pinned"
                            } else {
                                "Archived"
                            },
                            if item
                                .and_then(|i| i.fields.get(key))
                                .and_then(Value::as_bool)
                                .unwrap_or(false)
                            {
                                "true"
                            } else {
                                "false"
                            },
                            false,
                        );
                        field.kind = FieldKind::Bool;
                        fields.push(field);
                    }
                }
            }
            Workspace::Workflows => {
                let mut enabled = Field::text(
                    "enabled",
                    "Enabled",
                    if item
                        .and_then(|i| i.fields.get("enabled"))
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                    {
                        "true"
                    } else {
                        "false"
                    },
                    false,
                );
                enabled.kind = FieldKind::Bool;
                fields.push(enabled);
                if create {
                    fields.push(Field::text(
                        "step_title",
                        "Report step title",
                        "Create report",
                        true,
                    ));
                    fields.push(Field::multiline("step_prompt", "Report prompt", ""));
                }
                if !create
                    && let Some(node) = item
                        .and_then(|i| {
                            if self.workspace == Workspace::Apps && self.detail_tab == 1 {
                                i.fields.get("skills")
                            } else if self.workspace == Workspace::Projects && self.detail_tab == 1
                            {
                                i.fields.get("files")
                            } else if self.workspace == Workspace::Workflows && self.detail_tab == 1
                            {
                                i.fields.get("runs")
                            } else {
                                i.fields
                                    .get("nodes")
                                    .or_else(|| i.fields.pointer("/graph/nodes"))
                            }
                        })
                        .and_then(Value::as_array)
                        .and_then(|nodes| nodes.get(self.node_selected))
                {
                    fields.push(Field::text(
                        "node_id",
                        "Step ID",
                        text_field(node, "id"),
                        true,
                    ));
                    fields.push(Field::text(
                        "node_title",
                        "Step title",
                        text_field(node, "title"),
                        false,
                    ));
                    if let Some(config) = node.get("config").and_then(Value::as_object) {
                        for (key, value) in config {
                            if value.is_string() || value.is_boolean() || value.is_number() {
                                let label = key.replace('_', " ");
                                let text = value
                                    .as_str()
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| value.to_string());
                                let mut field =
                                    Field::text(&format!("config.{key}"), &label, &text, false);
                                if value.is_boolean() {
                                    field.kind = FieldKind::Bool;
                                }
                                if value.is_number() {
                                    field.kind = FieldKind::Number;
                                }
                                fields.push(field);
                            }
                        }
                    }
                }
            }
            _ => {}
        }
        let purpose = if create {
            FormPurpose::Create(workspace)
        } else {
            FormPurpose::Edit(workspace, item.unwrap().id.clone())
        };
        self.form = Some(Form::new(
            &format!(
                "{} {}",
                if create { "Create" } else { "Edit" },
                match workspace {
                    Workspace::Tasks => "Task",
                    Workspace::Projects => "Project",
                    _ => "Workflow",
                }
            ),
            purpose,
            fields,
        ));
    }
    fn delete_form(&mut self) {
        if let Some(item) = self.detail.as_ref().or_else(|| self.selected_item()) {
            self.form = Some(Form::new(
                &format!("Delete {}?", item.title),
                FormPurpose::Delete(self.workspace, item.id.clone()),
                vec![Field::text(
                    "confirmation",
                    "Type DELETE to permanently delete this item",
                    "",
                    true,
                )],
            ));
        }
    }
    fn question_form(&mut self, question: Value) {
        if self.cached_action_blocked() { return; }
        match questions::fields(&question) {
            Ok(fields) => {
                self.form = Some(Form::new(
                    question["question"].as_str().unwrap_or("Answer question"),
                    FormPurpose::Question(question.clone()),
                    fields,
                ))
            }
            Err(error) => self.status = error,
        }
    }
    fn cycle_field(&mut self, delta: i32) {
        let Some(field) = self
            .form
            .as_mut()
            .and_then(|form| form.fields.get_mut(form.selected))
        else {
            return;
        };
        match &field.kind {
            FieldKind::Bool => {
                let value = if field.editor.text.as_str() == "true" {
                    "false"
                } else {
                    "true"
                };
                field.editor = Editor::from(value);
            }
            FieldKind::Choice(options) => {
                if options.is_empty() {
                    return;
                }
                let selected = options
                    .iter()
                    .position(|v| v == field.editor.text.as_str())
                    .unwrap_or(0);
                let next = (selected as i32 + delta).rem_euclid(options.len() as i32) as usize;
                field.editor = Editor::from(&options[next]);
            }
            _ => {}
        }
    }
    fn form_key(&mut self, key: KeyEvent) -> Vec<UiCommand> {
        if self
            .form
            .as_ref()
            .is_some_and(|f| matches!(f.purpose, FormPurpose::Consent { .. }))
            && (key.code == KeyCode::Esc || key.code == KeyCode::Char('d'))
        {
            return self.activate(HitAction::DenyConsent);
        }

        if key.code == KeyCode::Esc {
            return self.cancel_form();
        }
        let form = self.form.as_mut().unwrap();
        if form.busy {
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::ShareResult { .. }) {
            return match key.code {
                KeyCode::Char('u') => self.activate(HitAction::RevealShare),
                KeyCode::Char('c') => self.activate(HitAction::CopyShare),
                KeyCode::Char('q') => self.activate(HitAction::QrShare),
                _ => vec![],
            };
        }
        if matches!(form.purpose, FormPurpose::AppConfirm { .. })
            && matches!(key.code, KeyCode::PageUp | KeyCode::PageDown)
        {
            if key.code == KeyCode::PageUp {
                form.scroll = form.scroll.saturating_sub(10);
            } else {
                form.scroll = form.scroll.saturating_add(10);
            }
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Help) {
            match key.code {
                KeyCode::Enter => self.form = None,
                KeyCode::Up => form.scroll = form.scroll.saturating_sub(1),
                KeyCode::Down => form.scroll = form.scroll.saturating_add(1),
                KeyCode::PageUp => form.scroll = form.scroll.saturating_sub(10),
                KeyCode::PageDown => form.scroll = form.scroll.saturating_add(10),
                _ => {}
            }
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Pairing) {
            if key.code == KeyCode::Enter {
                self.set_pair_pin_required();
            }
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Palette) {
            match key.code {
                KeyCode::Enter => {
                    let i = form.selected;
                    return self.activate(HitAction::Palette(i));
                }
                KeyCode::Up => form.selected = form.selected.saturating_sub(1),
                KeyCode::Down => form.selected = form.selected.saturating_add(1),
                _ => {
                    form.selected = 0;
                    self.palette_query.key(key);
                }
            }
            return vec![];
        }
        match key.code {
            KeyCode::Tab | KeyCode::Down
                if !matches!(key.code, KeyCode::Down)
                    || !form
                        .fields
                        .get(form.selected)
                        .is_some_and(|f| matches!(f.kind, FieldKind::Multiline)) =>
            {
                form.selected = (form.selected + 1) % (form.fields.len() + 1);
            }
            KeyCode::BackTab => {
                form.selected = if form.selected == 0 {
                    form.fields.len()
                } else {
                    form.selected - 1
                };
            }
            KeyCode::Enter
                if key.modifiers.contains(KeyModifiers::CONTROL)
                    || form.selected == form.fields.len() =>
            {
                return self.submit_form();
            }
            KeyCode::Enter => {
                if form
                    .fields
                    .get(form.selected)
                    .is_some_and(|f| matches!(f.kind, FieldKind::Multiline))
                {
                    form.fields[form.selected].editor.insert("\n");
                } else {
                    form.selected = (form.selected + 1) % (form.fields.len() + 1);
                }
            }
            KeyCode::Left | KeyCode::Right | KeyCode::Char(' ')
                if form
                    .fields
                    .get(form.selected)
                    .is_some_and(|f| matches!(f.kind, FieldKind::Choice(_) | FieldKind::Bool)) =>
            {
                self.cycle_field(if key.code == KeyCode::Left { -1 } else { 1 })
            }
            _ => {
                if let Some(field) = form.fields.get_mut(form.selected)
                    && !matches!(field.kind, FieldKind::Bool | FieldKind::Choice(_))
                {
                    field.editor.key(key);
                }
            }
        }
        vec![]
    }
    fn submit_form(&mut self) -> Vec<UiCommand> {
        if self.is_cached_chat_read_only() && self.form.as_ref().is_some_and(|form| matches!(&form.purpose,
            FormPurpose::Share(_) | FormPurpose::Question(_) | FormPurpose::Download(Workspace::Chats, _)
            | FormPurpose::Edit(Workspace::Chats, _) | FormPurpose::Delete(Workspace::Chats, _))) {
            self.cached_action_blocked(); return vec![];
        }
        let Some(form) = self.form.as_mut() else {
            return vec![];
        };
        if form.busy {
            return vec![];
        }
        for field in &form.fields {
            if field.required && field.editor.text.trim().is_empty() {
                form.error = format!("{} is required", field.label);
                return vec![];
            }
            if matches!(field.kind, FieldKind::Number)
                && !field.editor.text.is_empty()
                && field
                    .editor
                    .text
                    .parse::<f64>()
                    .map_or(true, |n| !n.is_finite())
            {
                form.error = format!("{} must be a number", field.label);
                return vec![];
            }
        }
        if matches!(form.purpose, FormPurpose::Login) && !form.fields[0].editor.text.contains('@') {
            form.error = "Enter a valid email address".into();
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Delete(..))
            && form.fields[0].editor.text.as_str() != "DELETE"
        {
            form.error = "Type DELETE to confirm".into();
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Share(_))
            && form.fields[1].editor.text.encode_utf16().count() > 10
        {
            form.error = "Link passwords are limited to ten characters".into();
            return vec![];
        }
        if matches!(form.purpose, FormPurpose::Download(..)) {
            let destination = std::path::Path::new(form.fields[0].editor.text.as_str());
            if destination.exists() && form.fields[1].editor.text.as_str() != "true" {
                form.error =
                    "Destination exists. Enable explicit overwrite confirmation to replace it."
                        .into();
                return vec![];
            }
        }
        if let FormPurpose::AppInput(skill) = &form.purpose {
            match apps::input(skill, &form.fields) {
                Err(error) => {
                    form.error = error;
                    return vec![];
                }
                Ok(input) => {
                    let skill = skill.clone();
                    let old = self.form.take().unwrap();
                    self.form = Some(Form::new(
                        &format!("Run {}? Running may spend credits", skill.title),
                        FormPurpose::AppConfirm {
                            skill,
                            input,
                            draft: old.fields,
                        },
                        vec![Field::text(
                            "confirm",
                            "Type RUN to execute and accept the credit charge",
                            "",
                            true,
                        )],
                    ));
                    self.hits.clear();
                    return vec![];
                }
            }
        }
        if matches!(form.purpose, FormPurpose::AppConfirm { .. })
            && form
                .fields
                .first()
                .is_none_or(|f| f.editor.text.as_str() != "RUN")
        {
            form.error = "Type RUN to explicitly confirm execution".into();
            return vec![];
        }
        let mut form = self.form.take().unwrap();
        let mut values = serde_json::Map::new();
        for field in &form.fields {
            if matches!(field.kind, FieldKind::Secret) {
                continue;
            }
            let value = if field.key == "priority"
                && matches!(
                    form.purpose,
                    FormPurpose::Create(Workspace::Tasks) | FormPurpose::Edit(Workspace::Tasks, _)
                ) {
                json!(match field.editor.text.as_str() {
                    "low" => 1,
                    "medium" => 2,
                    "high" => 3,
                    "urgent" => 4,
                    _ => 0,
                })
            } else {
                match &field.kind {
                    FieldKind::Bool => Value::Bool(field.editor.text.as_str() == "true"),
                    FieldKind::Number => {
                        serde_json::from_str(&field.editor.text).unwrap_or(Value::Null)
                    }
                    _ => Value::String(field.editor.text.to_string()),
                }
            };
            values.insert(field.key.clone(), value);
        }
        if matches!(form.purpose, FormPurpose::Create(Workspace::Workflows)) {
            let title = values
                .remove("step_title")
                .unwrap_or(json!("Create report"));
            let prompt = values.remove("step_prompt").unwrap_or(json!(""));
            values.insert("graph".into(),json!({"nodes":[{"id":"trigger","type":"trigger","title":"Manual trigger","config":{}},{"id":"report","type":"create_chat_report","title":title,"config":{"prompt":prompt}}],"edges":[{"source":"trigger","target":"report"}]}));
        }
        if matches!(form.purpose, FormPurpose::Edit(Workspace::Workflows, _))
            && let Some(item) = self.detail.as_ref().or_else(|| self.selected_item())
        {
            let mut graph=item.fields.get("graph").cloned().unwrap_or_else(||json!({"nodes":item.fields.get("nodes").cloned().unwrap_or(json!([])),"edges":item.fields.get("edges").cloned().unwrap_or(json!([]))}));
            if let Some(id) = values
                .remove("node_id")
                .and_then(|v| v.as_str().map(str::to_owned))
                && let Some(nodes) = graph.get_mut("nodes").and_then(Value::as_array_mut)
                && let Some(node) = nodes.iter_mut().find(|n| n["id"] == id)
            {
                if let Some(title) = values.remove("node_title") {
                    node["title"] = title;
                }
                let config = values
                    .keys()
                    .filter(|k| k.starts_with("config."))
                    .cloned()
                    .collect::<Vec<_>>();
                for key in config {
                    if let Some(value) = values.remove(&key) {
                        node["config"][key.trim_start_matches("config.")] = value;
                    }
                }
            }
            values.insert("graph".into(), graph);
        }
        let command = match &form.purpose {
            FormPurpose::AppConfirm { skill, input, .. } => {
                let (app, skill_id) = match apps::identifiers(skill) {
                    Ok(ids) => ids,
                    Err(error) => {
                        form.error = error;
                        self.form = Some(form);
                        return vec![];
                    }
                };
                UiCommand::Mutate(Mutation::Create {
                    workspace: Workspace::Apps,
                    fields: json!({"app":app,"skill":skill_id,"input":input}),
                })
            }
            FormPurpose::Consent { request_id, items } => UiCommand::Consent {
                request_id: request_id.clone(),
                approved_ids: items
                    .iter()
                    .filter(|item| {
                        form.fields.iter().any(|field| {
                            field.key == item.id && field.editor.text.as_str() == "true"
                        })
                    })
                    .map(|item| item.id.clone())
                    .collect(),
            },
            FormPurpose::Login => UiCommand::Login {
                email: form.fields[0].editor.take().to_string(),
                password: form.fields[1].editor.take(),
                tfa: form
                    .fields
                    .get_mut(2)
                    .map(|f| f.editor.take().to_string())
                    .filter(|s| !s.is_empty()),
            },
            FormPurpose::Unlock => UiCommand::Unlock {
                passphrase: form.fields[0].editor.take(),
            },
            FormPurpose::PairPin => UiCommand::PairPin {
                pin: form.fields[0].editor.take(),
                vault_passphrase: form
                    .fields
                    .get_mut(1)
                    .map(|f| f.editor.take())
                    .filter(|s| !s.is_empty()),
            },
            FormPurpose::Share(chat_id) => UiCommand::Share {
                chat_id: chat_id.clone(),
                expires_in: match form.fields[0].editor.text.as_str() {
                    "1 minute" => 60,
                    "1 hour" => 3600,
                    "1 day" => 86400,
                    "1 week" => 604800,
                    "2 weeks" => 1209600,
                    "1 month" => 2592000,
                    "3 months" => 7776000,
                    "No expiration" => 0,
                    _ => 86400,
                },
                password: form.fields[1].editor.take(),
                include_sensitive: false,
            },
            FormPurpose::Download(workspace, id) => UiCommand::Download {
                workspace: *workspace,
                id: id.clone(),
                destination: std::path::PathBuf::from(form.fields[0].editor.text.as_str()),
                overwrite: form.fields[1].editor.text.as_str() == "true",
            },
            FormPurpose::Team => {
                UiCommand::SwitchTeam(if form.fields[0].editor.text.trim().is_empty() {
                    None
                } else {
                    Some(form.fields[0].editor.text.trim().to_owned())
                })
            }
            FormPurpose::Create(workspace) => UiCommand::Mutate(Mutation::Create {
                workspace: *workspace,
                fields: Value::Object(values),
            }),
            FormPurpose::Edit(workspace, id) => UiCommand::Mutate(Mutation::Update {
                workspace: *workspace,
                id: id.clone(),
                fields: Value::Object(values),
            }),
            FormPurpose::Settings(route) => UiCommand::Mutate(Mutation::SetSetting {
                section: route.clone(),
                fields: Value::Object(values),
            }),
            FormPurpose::Delete(workspace, id) => UiCommand::Mutate(Mutation::Delete {
                workspace: *workspace,
                id: id.clone(),
            }),
            FormPurpose::Question(question) => match questions::response(question, &form.fields) {
                Ok(text) => UiCommand::Send {
                    chat_id: self.chat.as_ref().map(|c| c.id.clone()),
                    text,
                },
                Err(error) => {
                    form.error = error;
                    self.form = Some(form);
                    return vec![];
                }
            },

            _ => return vec![],
        };
        self.status = "Submitting…".into();
        // Keep mutation drafts until runtime acknowledges completion; secrets are already moved out.
        if matches!(
            form.purpose,
            FormPurpose::Create(..)
                | FormPurpose::Edit(..)
                | FormPurpose::Settings(..)
                | FormPurpose::AppConfirm { .. }
        ) {
            form.busy = true;
            form.error.clear();
            self.form = Some(form);
        }
        self.hits.clear();
        vec![command]
    }
    pub fn mutation_succeeded(&mut self) {
        self.form = None;
        self.status = "Saved".into();
        self.hits.clear();
    }
    pub fn set_busy(&mut self, busy: bool) {
        if let Some(form) = self.form.as_mut() {
            form.busy = busy;
            if !busy
                && form.error.is_empty()
                && matches!(
                    form.purpose,
                    FormPurpose::Create(..)
                        | FormPurpose::Edit(..)
                        | FormPurpose::Settings(..)
                        | FormPurpose::AppConfirm { .. }
                )
            {
                self.form = None;
            }
        }
    }
    pub fn clear_private(&mut self) {
        self.chat_layout = None;
        self.embed_offsets.clear();
        self.items = std::array::from_fn(|_| vec![]);
        self.selected = [0; 6];
        self.chat = None;
        self.cached_chat_state = None;
        self.detail = None;
        self.detail_links.clear();
        self.origin = None;
        self.chat_origin = None;
        self.app_history.clear();
        self.draft.clear();
        self.drafts.clear();
        self.pending_send = None;
        self.active_turn = None;
        self.delivery = Delivery::Staged;
        self.uncertain_turns.clear();
        self.last_uncertain = None;
        self.palette_query.clear();
        self.form = None;
        self.settings = None;
        self.username.clear();
        self.authenticated = false;
        self.streaming = false;
        self.scroll = 0;
        self.hits.clear();
    }
    fn palette_actions(&self) -> Vec<(&'static str, &'static str)> {
        const ACTIONS: &[(&str, &str)] = &[
            ("New chat", "/new"),
            ("Chats", "/chats"),
            ("Apps", "/apps"),
            ("Use selected app skill", "/app-run"),
            ("Projects", "/projects"),
            ("Workflows", "/workflows"),
            ("Tasks", "/tasks"),
            ("Settings", "/settings"),
            ("Share current chat", "/share"),
            ("Download current item", "/download"),
            ("Switch Team", "/team"),
            ("Create Task", "/task-create"),
            ("Create Project", "/project-create"),
            ("Create Workflow", "/workflow-create"),
            ("Refresh", "/refresh"),
            ("Toggle sidebar", "/sidebar"),
            ("Check pending delivery", "/pending"),
            ("Copy pending message", "/copy-pending"),
            ("Retry failed message", "/retry"),
            ("Stop response", "/stop"),
            ("Sign in", "/login"),
            ("Pair terminal", "/pair"),
            ("Sign out", "/logout"),
            ("Help", "/help"),
            ("Exit", "/exit"),
        ];
        let needle = self.palette_query.text.to_lowercase();
        ACTIONS
            .iter()
            .copied()
            .filter(|(label, command)| {
                format!("{label} {command}")
                    .to_lowercase()
                    .contains(&needle)
            })
            .collect()
    }
    pub fn draw(&mut self, frame: &mut Frame) {
        let area = frame.area();
        if self.size != (area.width, area.height) {
            self.resize(area.width, area.height);
        }
        self.hits.clear();
        frame.render_widget(
            Block::default().style(Style::default().bg(BASE).fg(TEXT)),
            area,
        );
        if area.width < 12 || area.height < 5 {
            frame.render_widget(
                Paragraph::new("Resize terminal").style(Style::default().fg(TEXT)),
                area,
            );
            return;
        }
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(2),
                Constraint::Min(1),
                Constraint::Length(1),
            ])
            .split(area);
        self.draw_header(frame, chunks[0]);
        let mut main = chunks[1];
        let narrow_sidebar = self.sidebar && area.width < 96;
        let split_settings = self.settings.is_some() && area.width >= 120;
        let settings_area = if split_settings {
            let width = (main.width / 3).clamp(38, 54);
            let r = Rect::new(main.right() - width, main.y, width, main.height);
            main.width = main.width.saturating_sub(width + 1);
            r
        } else {
            main
        };
        if self.sidebar && !narrow_sidebar {
            let sidebar_width = (main.width / 4).clamp(20, 30);
            let sidebar_rect = Rect::new(main.x, main.y, sidebar_width, main.height);
            self.draw_sidebar(frame, sidebar_rect);
            main.x += sidebar_width + 1;
            main.width = main.width.saturating_sub(sidebar_width + 1);
        }
        if main.width > 0 {
            self.draw_main(frame, main);
        }
        if narrow_sidebar {
            let rect = Rect::new(
                chunks[1].x,
                chunks[1].y,
                chunks[1].width.min(34),
                chunks[1].height,
            );
            frame.render_widget(Clear, rect);
            self.hits.clear();
            self.draw_sidebar(frame, rect);
        }
        if self.settings.is_some() {
            if !split_settings {
                self.hits.clear();
            }
            frame.render_widget(Clear, settings_area);
            let previous_scroll = self.scroll;
            self.draw_settings(frame, settings_area);
            self.scroll = previous_scroll;
        }
        let presentation_status = if self.is_cached_chat_read_only() {
            format!("Cached chat · {} · recent messages only │ {}", if self.cached_chat_state == Some(CachedChatState::Offline) { "offline" } else { "refreshing" }, self.status)
        } else { self.status.clone() };
        let status = if self.selecting {
            format!(" Selection mode · Ctrl+Y pointer mode  │  {}", presentation_status)
        } else {
            format!(" {}  │  Ctrl+K actions · F1 help", presentation_status)
        };
        frame.render_widget(
            Paragraph::new(status).style(Style::default().bg(PANEL).fg(MUTED)),
            chunks[2],
        );
        if self.form.is_some() {
            self.hits.clear();
            self.draw_form(frame, area);
        }
    }
    fn draw_header(&mut self, frame: &mut Frame, area: Rect) {
        frame.render_widget(Block::default().style(Style::default().bg(PANEL)), area);
        let mut x = area.x;
        let menu = " ☰ ";
        self.button(
            frame,
            Rect::new(x, area.y, 4, 1),
            menu,
            HitAction::Sidebar,
            self.sidebar,
        );
        x += 4;
        let settings_width = if area.width >= 60 { 12 } else { 4 };
        let right = area.right().saturating_sub(settings_width);
        let labels: Vec<(Workspace, String)> = Workspace::ALL[..5]
            .iter()
            .copied()
            .map(|w| {
                (
                    w,
                    if area.width < 63 {
                        w.label().chars().take(1).collect()
                    } else {
                        w.label().to_owned()
                    },
                )
            })
            .collect();
        for (workspace, label) in labels {
            let width = label.width() as u16 + 2;
            if x + width > right {
                break;
            }
            self.button(
                frame,
                Rect::new(x, area.y, width, 1),
                &format!(" {label} "),
                HitAction::Nav(workspace),
                self.workspace == workspace,
            );
            x += width;
        }
        if self.focus != Focus::Navigation && right.saturating_sub(x) >= 20 {
            frame.render_widget(
                Paragraph::new(NAVIGATION_HINT).style(Style::default().fg(MUTED)),
                Rect::new(x + 1, area.y, right - x - 1, 1),
            );
        }
        let label = if settings_width > 4 {
            " ⚙ Settings "
        } else {
            " ⚙ "
        };
        self.button(
            frame,
            Rect::new(right, area.y, settings_width, 1),
            label,
            HitAction::Settings,
            self.settings.is_some(),
        );
        frame.render_widget(
            Paragraph::new(if self.focus == Focus::Navigation {
                format!("Navigate: {} · ←/→ · Enter · Esc", Workspace::ALL[self.navigation_index].label())
            } else {
                "─".repeat(area.width as usize)
            }).style(Style::default().fg(if self.focus == Focus::Navigation { ACCENT } else { BORDER })),
            Rect::new(area.x, area.y + 1, area.width, 1),
        );
    }
    fn button(
        &mut self,
        frame: &mut Frame,
        rect: Rect,
        label: &str,
        action: HitAction,
        active: bool,
    ) {
        frame.render_widget(
            Paragraph::new(markdown::clean(label)).style(
                Style::default()
                    .fg(if active { ACCENT } else { TEXT })
                    .add_modifier(if active {
                        Modifier::BOLD
                    } else {
                        Modifier::empty()
                    }),
            ),
            rect,
        );
        self.hit(rect, action);
    }
    fn draw_sidebar(&mut self, frame: &mut Frame, area: Rect) {
        frame.render_widget(panel(" Recent chats ", self.focus == Focus::Sidebar), area);
        let inner = inset(area, 1, 1);
        if inner.height == 0 {
            return;
        }
        self.button(
            frame,
            Rect::new(inner.x, inner.y, inner.width, 1),
            "＋ New chat",
            HitAction::NewChat,
            false,
        );
        let chats = self.items[0].clone();
        let visible = inner.height.saturating_sub(2) as usize;
        let offset = self.selected[0].saturating_sub(visible.saturating_sub(1));
        for (row, (i, item)) in chats
            .iter()
            .enumerate()
            .filter(|(_, item)| !item.id.starts_with("embed:"))
            .skip(offset)
            .take(visible)
            .enumerate()
        {
            let rect = Rect::new(inner.x, inner.y + row as u16 + 2, inner.width, 1);
            self.button(
                frame,
                rect,
                &format!(
                    "{} {}",
                    if self.selected[0] == i { "›" } else { " " },
                    item.title
                ),
                HitAction::SidebarItem(i),
                self.selected[0] == i && self.focus == Focus::Sidebar,
            );
        }
    }
    fn draw_main(&mut self, frame: &mut Frame, area: Rect) {
        let composer_height = if area.height >= 10 {
            let (rows, _) = self
                .draft
                .display(area.width.min(100).saturating_sub(4) as usize, false);
            (rows.len() as u16 + 2).clamp(3, 7).min(area.height / 2)
        } else {
            3.min(area.height)
        };
        let content = Rect::new(
            area.x,
            area.y,
            area.width,
            area.height.saturating_sub(composer_height + 1),
        );
        if content.height > 0 {
            if self.chat.is_some() {
                self.draw_chat(frame, content);
            } else if self.detail.is_some() {
                self.draw_detail(frame, content);
            } else if self.workspace == Workspace::Tasks {
                self.draw_tasks(frame, content);
            } else {
                self.draw_home(frame, content);
            }
        }
        let width = area.width.min(100);
        let composer = Rect::new(
            area.x + (area.width - width) / 2,
            area.bottom().saturating_sub(composer_height),
            width,
            composer_height,
        );
        let title = if self.is_cached_chat_read_only() {
            if self.cached_chat_state == Some(CachedChatState::Offline) { " Cached chat · offline · draft preserved " } else { " Cached chat · refreshing · draft preserved " }
        } else if self.visible_chat_streaming() {
            " Response streaming · Ctrl+C stop "
        } else {
            " Message · Enter send · Alt+Enter newline "
        };
        frame.render_widget(panel(title, self.focus == Focus::Composer), composer);
        let inner = inset(composer, 1, 1);
        self.composer_rect = inner;
        self.hit(inner, HitAction::Composer);
        let (rows, (col, row)) = self.draft.display(inner.width as usize, false);
        self.composer_offset = row.saturating_sub(inner.height.saturating_sub(1) as usize);
        let lines = rows
            .into_iter()
            .skip(self.composer_offset)
            .take(inner.height as usize)
            .map(Line::from)
            .collect::<Vec<_>>();
        if self.draft.text.is_empty() {
            frame.render_widget(
                Paragraph::new(if self.authenticated {
                    "Ask anything, or /help"
                } else {
                    "Sign in to send messages · /login"
                })
                .style(Style::default().fg(MUTED)),
                inner,
            );
        } else {
            frame.render_widget(
                Paragraph::new(lines).style(Style::default().fg(TEXT)),
                inner,
            );
        }
        if self.focus == Focus::Composer
            && self.form.is_none()
            && !(self.settings.is_some() && self.size.0 < 120)
            && inner.width > 0
            && inner.height > 0
        {
            frame.set_cursor_position((
                inner.x + (col as u16).min(inner.width - 1),
                inner.y + (row.saturating_sub(self.composer_offset) as u16).min(inner.height - 1),
            ));
        }
    }
    fn draw_home(&mut self, frame: &mut Frame, area: Rect) {
        // TS home banner: category-colored band with the day's inspiration.
        let area = match self.inspirations.get(self.inspiration_index) {
            Some(inspiration) if self.workspace == Workspace::Chats && area.height >= 30 => {
                let title = inspiration.feature_title.as_deref().filter(|t| !t.is_empty()).unwrap_or(
                    if inspiration.title.is_empty() { "Daily inspiration" } else { &inspiration.title },
                );
                let band = Rect::new(area.x, area.y, area.width, 6);
                let text = vec![
                    Line::from("DAILY INSPIRATION  ‹  Ctrl+O explore  ›"),
                    Line::default(),
                    Line::from(markdown::clean(&inspiration.phrase)),
                    Line::from(Span::styled(markdown::clean(title), Style::default().bold())),
                ];
                frame.render_widget(
                    Paragraph::new(text)
                        .wrap(Wrap { trim: true })
                        .alignment(ratatui::layout::Alignment::Center)
                        .style(Style::default().fg(Color::White).bg(app_color(&inspiration.category))),
                    band,
                );
                Rect::new(area.x, area.y + 7, area.width, area.height - 7)
            }
            _ => area,
        };
        let title = if self.workspace == Workspace::Chats {
            if self.username.is_empty() && !self.authenticated && self.items[0].is_empty() {
                "Welcome to OpenMates".to_owned()
            } else if self.username.is_empty() {
                // Signed in, name not yet known: the TS home's fallback greeting.
                "Hey there!".to_owned()
            } else {
                format!("Hey {}!", self.username)
            }
        } else {
            self.workspace.label().into()
        };
        frame.render_widget(
            Paragraph::new(title)
                .alignment(ratatui::layout::Alignment::Center)
                .style(Style::default().fg(TEXT).bold()),
            Rect::new(area.x, area.y + u16::from(area.height > 5), area.width, 1),
        );
        let help = match self.workspace {
            Workspace::Chats => "Continue where you left off",
            Workspace::Apps => "Choose an app · ←/→ choose · Enter explore",
            Workspace::Projects => "Your Projects · n create · Enter open",
            Workspace::Workflows => "Automate with Workflows · n create · Enter open",
            _ => "",
        };
        if area.height > 3 {
            frame.render_widget(
                Paragraph::new(help)
                    .alignment(ratatui::layout::Alignment::Center)
                    .style(Style::default().fg(MUTED)),
                Rect::new(area.x, area.y + 3, area.width, 1),
            );
        }
        let cards = Rect::new(
            area.x,
            area.y + (5.min(area.height)),
            area.width,
            area.height.saturating_sub(5),
        );
        self.draw_cards(frame, cards);
        if self.items[index(self.workspace)].is_empty() && cards.height > 1 {
            let message = if self.authenticated {
                "No items available · Ctrl+R refresh"
            } else {
                "Sign in or pair this terminal to load your encrypted workspace"
            };
            frame.render_widget(
                Paragraph::new(message)
                    .wrap(Wrap { trim: false })
                    .alignment(ratatui::layout::Alignment::Center)
                    .style(Style::default().fg(MUTED)),
                cards,
            );
        }
    }
    fn draw_cards(&mut self, frame: &mut Frame, area: Rect) {
        if area.width < 4 || area.height < 2 {
            return;
        }
        let items = self.items[index(self.workspace)].clone();
        if items.is_empty() {
            return;
        }
        let count = (area.width / 30).clamp(1, 4) as usize;
        let selected = self.selected[index(self.workspace)];
        let start = (selected / count) * count;
        let card_width = area.width / count as u16;
        for (column, (i, item)) in items.iter().enumerate().skip(start).take(count).enumerate() {
            let rect = Rect::new(
                area.x + column as u16 * card_width,
                area.y,
                card_width.saturating_sub(1),
                area.height.min(10),
            );
            let active = i == selected;
            let heading = if item.title.trim().is_empty() && self.workspace == Workspace::Chats {
                "Untitled chat".to_owned()
            } else {
                item.title.clone()
            };
            frame.render_widget(
                panel(
                    format!(" {} ", heading),
                    active && self.focus == Focus::Content,
                ),
                rect,
            );
            let inner = inset(rect, 1, 1);
            let mut lines = vec![
                Line::from(Span::styled(
                    markdown::clean(&heading),
                    Style::default().fg(app_color(&item.category)).bold(),
                )),
                Line::default(),
                Line::from(markdown::clean(&item.description)),
            ];
            if !item.status.is_empty() {
                lines.push(Line::from(Span::styled(
                    format!("● {}", item.status.replace('_', " ")),
                    Style::default().fg(task_color(&item.status)),
                )));
            }
            let mut body = inner;
            if self.workspace == Workspace::Chats && inner.height > 3 {
                // TS home footer: due-soon label, else the category, else "Chat".
                let footer = item.fields.get("footer").and_then(|value| value.as_str()).map(str::to_owned)
                    .or_else(|| Some(item.category.replace('_', " ")).filter(|category| !category.is_empty()))
                    .unwrap_or_else(|| "Chat".to_owned());
                body.height = inner.height - 2;
                frame.render_widget(
                    Paragraph::new(Line::from(Span::styled(footer, Style::default().fg(MUTED)))),
                    Rect::new(inner.x, inner.bottom() - 1, inner.width, 1),
                );
            }
            frame.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), body);
            self.hit(rect, HitAction::Open(i));
        }
        if area.height > 11 {
            self.button(
                frame,
                Rect::new(area.x, area.y + 11, 3, 1),
                " ‹ ",
                HitAction::NextCard(-1),
                false,
            );
            frame.render_widget(
                Paragraph::new(format!(
                    "{}{} of {}",
                    if self.workspace == Workspace::Chats {
                        if items.iter().any(|item| item.id.starts_with("embed:")) { "Item " } else { "Chat " }
                    } else {
                        ""
                    },
                    selected + 1,
                    items.len()
                ))
                    .alignment(ratatui::layout::Alignment::Center)
                    .style(Style::default().fg(MUTED)),
                Rect::new(area.x + 3, area.y + 11, area.width.saturating_sub(6), 1),
            );
            self.button(
                frame,
                Rect::new(area.right() - 3, area.y + 11, 3, 1),
                " › ",
                HitAction::NextCard(1),
                false,
            );
            if self.workspace == Workspace::Chats && area.height > 15 {
                frame.render_widget(
                    Paragraph::new("←/→ choose  ·  Enter open  ·  Tab write")
                        .alignment(ratatui::layout::Alignment::Center)
                        .style(Style::default().fg(MUTED)),
                    Rect::new(area.x, area.y + 12, area.width, 1),
                );
                frame.render_widget(
                    Paragraph::new("/search Search chats  ·  Ctrl+N New chat")
                        .alignment(ratatui::layout::Alignment::Center)
                        .style(Style::default().fg(MUTED)),
                    Rect::new(area.x, area.y + 13, area.width, 1),
                );
                if self.running_chat_id().is_some() && area.height > 16 {
                    frame.render_widget(
                        Paragraph::new("1 chat active…  /active")
                            .alignment(ratatui::layout::Alignment::Center)
                            .style(Style::default().fg(MUTED)),
                        Rect::new(area.x, area.y + 15, area.width, 1),
                    );
                }
            }
        }
    }
    fn draw_tasks(&mut self, frame: &mut Frame, area: Rect) {
        let header = Rect::new(area.x, area.y, area.width, 1);
        frame.render_widget(
            Paragraph::new("Tasks").style(Style::default().fg(TEXT).bold()),
            header,
        );
        if area.width > 18
            && matches!(
                self.workspace,
                Workspace::Projects | Workspace::Tasks | Workspace::Workflows
            )
        {
            self.button(
                frame,
                Rect::new(area.right() - 12, area.y, 12, 1),
                "＋ New Task",
                HitAction::Create,
                false,
            );
        }
        let statuses = [
            ("backlog", "Backlog"),
            ("todo", "To do"),
            ("in_progress", "In progress"),
            ("blocked", "Blocked"),
            ("done", "Done"),
        ];
        let tasks = self.items[4].clone();
        let selected = self.selected[4];
        let columns = if area.width >= 115 {
            5
        } else if area.width >= 70 {
            3
        } else {
            1
        };
        let active_status = tasks
            .get(selected)
            .map(|t| task_group(&t.status))
            .unwrap_or("todo");
        let selected_column = statuses
            .iter()
            .position(|(s, _)| *s == active_status)
            .unwrap_or(1);
        let start = if columns == 5 {
            0
        } else {
            selected_column.saturating_sub(columns / 2).min(5 - columns)
        };
        let width = area.width / columns as u16;
        for (column, (_, (status, label))) in statuses
            .iter()
            .enumerate()
            .skip(start)
            .take(columns)
            .enumerate()
        {
            let rect = Rect::new(
                area.x + column as u16 * width,
                area.y + 2,
                width.saturating_sub(1),
                area.height.saturating_sub(2),
            );
            let color = task_color(status);
            frame.render_widget(
                panel(format!(" {label} "), false).border_style(Style::default().fg(color)),
                rect,
            );
            let inner = inset(rect, 1, 1);
            let matching = tasks
                .iter()
                .enumerate()
                .filter(|(_, task)| task_group(&task.status) == *status)
                .collect::<Vec<_>>();
            let count = matching.len();
            let selected_row = matching
                .iter()
                .position(|(i, _)| *i == selected)
                .unwrap_or(0);
            let visible = (inner.height / 4).max(1) as usize;
            let offset = selected_row.saturating_sub(visible.saturating_sub(1));
            for (row, (i, task)) in matching.into_iter().skip(offset).take(visible).enumerate() {
                let card = Rect::new(
                    inner.x,
                    inner.y + row as u16 * 4,
                    inner.width,
                    3.min(inner.height.saturating_sub(row as u16 * 4)),
                );
                if card.height == 0 {
                    continue;
                }
                let active = i == selected;
                let style = Style::default()
                    .fg(if active { ACCENT } else { TEXT })
                    .bg(if active { BORDER } else { PANEL });
                frame.render_widget(
                    Paragraph::new(vec![
                        Line::from(Span::styled(
                            format!(
                                "{} {}",
                                if active { "▸" } else { " " },
                                markdown::clean(&task.title)
                            ),
                            style.bold(),
                        )),
                        Line::from(Span::styled(
                            format!("  {}", text_field(&task.fields, "priority")),
                            Style::default().fg(MUTED),
                        )),
                    ])
                    .style(style)
                    .wrap(Wrap { trim: false }),
                    card,
                );
                self.hit(card, HitAction::Open(i));
            }
            if count == 0 && inner.height > 0 {
                frame.render_widget(
                    Paragraph::new("No tasks").style(Style::default().fg(MUTED)),
                    inner,
                );
            }
        }
    }
    fn content_links(&self) -> Vec<Link> {
        let mut links = vec![];
        if let Some((_, rows)) = &self.chat_layout {
            for part in rows.iter().flatten() {
                if let Some(link) = &part.link
                    && !links.contains(link)
                {
                    links.push(link.clone());
                }
            }
        }
        links
    }
    fn draw_chat(&mut self, frame: &mut Frame, area: Rect) {
        let Some(chat) = self.chat.as_ref() else {
            return;
        };
        let title = chat.title.clone();
        let width = area.width.min(110);
        let area = Rect::new(
            area.x + (area.width - width) / 2,
            area.y,
            width,
            area.height,
        );
        let mut x = area.x;
        self.button(
            frame,
            Rect::new(x, area.y, 7, 1),
            "‹ Back",
            HitAction::Back,
            false,
        );
        x += 7;
        let actions = if area.width > 75 {
            39
        } else if area.width > 32 {
            17
        } else {
            7
        };
        frame.render_widget(
            Paragraph::new(chat_title_line(&markdown::clean(&title), area.width.saturating_sub(7 + actions))),
            Rect::new(x, area.y, area.width.saturating_sub(7 + actions), 1),
        );
        if area.width > 32 {
            self.button(
                frame,
                Rect::new(area.right() - 17, area.y, 9, 1),
                " ⧉ Copy",
                HitAction::Copy,
                false,
            );
            if area.width > 75 {
                self.button(
                    frame,
                    Rect::new(area.right() - 39, area.y, 10, 1),
                    "Share",
                    HitAction::Share,
                    false,
                );
                self.button(
                    frame,
                    Rect::new(area.right() - 29, area.y, 12, 1),
                    "Download",
                    HitAction::Download,
                    false,
                );
            }
        }
        self.button(
            frame,
            Rect::new(area.right() - 7, area.y, 7, 1),
            " Close",
            HitAction::Close,
            false,
        );
        let body = Rect::new(
            area.x,
            area.y + 2,
            area.width,
            area.height.saturating_sub(2),
        );
        let cached = self.chat_layout.take();
        let rows = if let Some((width, rows)) = cached.filter(|(width, _)| *width == body.width) {
            let _ = width;
            rows
        } else {
            let chat = self.chat.as_ref().unwrap();
            let mut rows: Vec<Row> = vec![];
            for message in &chat.messages {
                let user = message.role == "user";
                let label = if user {
                    "You"
                } else if !message.sender.is_empty() {
                    &message.sender
                } else {
                    "OpenMates"
                };
                let color = if user {
                    MUTED
                } else {
                    app_color(&chat.category)
                };
                rows.push(markdown::styled(label, Style::default().fg(color).bold()));
                if !message.thinking.is_empty() {
                    rows.push(markdown::styled(
                        if self.visible_chat_streaming() {
                            "Thinking…"
                        } else {
                            "Thought process available in chat export"
                        },
                        Style::default().fg(MUTED).italic(),
                    ));
                }
                rows.extend(markdown::render(
                    &message.content,
                    body.width.saturating_sub(2) as usize,
                ));
                if !message.embeds.is_empty() {
                    rows.push(vec![]);
                    let offset = self
                        .embed_offsets
                        .get(&message.id)
                        .copied()
                        .unwrap_or(0)
                        .min(message.embeds.len().saturating_sub(1));
                    rows.extend(embed_rows(&message.embeds[offset..], body.width as usize));
                    if message.embeds.len() > 1 {
                        rows.push(vec![
                            markdown::Part {
                                text: "‹ Previous result  ".into(),
                                style: Style::default().fg(BLUE),
                                link: Some(Link::Carousel {
                                    message: message.id.clone(),
                                    delta: -1,
                                }),
                            },
                            markdown::Part {
                                text: format!("{} / {}  ", offset + 1, message.embeds.len()),
                                style: Style::default().fg(MUTED),
                                link: None,
                            },
                            markdown::Part {
                                text: "Next result ›".into(),
                                style: Style::default().fg(BLUE),
                                link: Some(Link::Carousel {
                                    message: message.id.clone(),
                                    delta: 1,
                                }),
                            },
                        ]);
                    }
                }
                rows.push(vec![]);
                rows.push(vec![]);
            }
            if self.visible_chat_streaming() {
                rows.push(markdown::styled(
                    "● Responding…",
                    Style::default().fg(ACCENT),
                ));
            }
            rows
        };
        self.paint_rows(frame, body, &rows, self.follow_tail);
        self.chat_layout = Some((body.width, rows));
    }
    fn paint_rows(&mut self, frame: &mut Frame, area: Rect, rows: &[Row], tail: bool) {
        let mut links = vec![];
        if self.chat.is_some() && self.focus == Focus::Content {
            for part in rows.iter().flatten() {
                if let Some(link) = &part.link
                    && !links.contains(link)
                {
                    links.push(link.clone());
                }
            }
        }
        let active_link = if self.chat.is_some() {
            links.get(self.content_action).cloned()
        } else {
            self.detail_links.get(self.node_selected).cloned()
        };

        let max_scroll = rows.len().saturating_sub(area.height as usize);
        if tail {
            self.scroll = max_scroll;
        } else {
            self.scroll = self.scroll.min(max_scroll);
        }
        for (y, row) in rows
            .iter()
            .skip(self.scroll)
            .take(area.height as usize)
            .enumerate()
        {
            let mut x = area.x;
            let rect = Rect::new(area.x, area.y + y as u16, area.width, 1);
            let line = Line::from(
                row.iter()
                    .map(|part| {
                        Span::styled(
                            part.text.clone(),
                            if part
                                .link
                                .as_ref()
                                .is_some_and(|link| active_link.as_ref() == Some(link))
                            {
                                part.style.fg(ACCENT).add_modifier(Modifier::BOLD)
                            } else {
                                part.style
                            },
                        )
                    })
                    .collect::<Vec<_>>(),
            );
            frame.render_widget(Paragraph::new(line), rect);
            for part in row {
                let width = (part.text.width() as u16).min(area.right().saturating_sub(x));
                if let Some(link) = &part.link {
                    self.hit(
                        Rect::new(x, rect.y, width, 1),
                        HitAction::Link(link.clone()),
                    );
                }
                x = x.saturating_add(width);
                if x >= area.right() {
                    break;
                }
            }
        }
        if max_scroll > 0 && area.width > 0 {
            let thumb = area.y
                + ((area.height.saturating_sub(1) as usize * self.scroll) / max_scroll) as u16;
            frame.render_widget(
                Paragraph::new("▐").style(Style::default().fg(MUTED)),
                Rect::new(area.right() - 1, thumb, 1, 1),
            );
        }
    }
    fn draw_detail(&mut self, frame: &mut Frame, area: Rect) {
        let Some(item) = self.detail.clone() else {
            return;
        };
        self.button(
            frame,
            Rect::new(area.x, area.y, 7.min(area.width), 1),
            "‹ Back",
            HitAction::Back,
            false,
        );
        if self.workspace == Workspace::Apps
            && item.fields.get("input_schema").is_some()
            && area.width > 18
        {
            self.button(
                frame,
                Rect::new(area.right() - 17, area.y, 17, 1),
                "Use skill · Enter",
                HitAction::SkillRun,
                false,
            );
        }
        if area.width > 18
            && matches!(
                self.workspace,
                Workspace::Projects | Workspace::Tasks | Workspace::Workflows
            )
        {
            self.button(
                frame,
                Rect::new(area.right() - 17, area.y, 8, 1),
                " Edit",
                HitAction::Edit,
                false,
            );
            self.button(
                frame,
                Rect::new(area.right() - 9, area.y, 9, 1),
                " Delete",
                HitAction::Delete,
                false,
            );
        }
        if area.height < 5 {
            return;
        }
        frame.render_widget(
            Paragraph::new(markdown::clean(&item.title))
                .alignment(ratatui::layout::Alignment::Center)
                .style(Style::default().fg(app_color(&item.category)).bold()),
            Rect::new(area.x, area.y + 2, area.width, 1),
        );
        let tabs: &[&str] = match self.workspace {
            Workspace::Projects => &["Overview", "Files", "Tasks"],
            Workspace::Workflows => &["Graph", "Runs"],
            Workspace::Tasks => &["Overview", "Activity"],
            Workspace::Apps
                if item.fields.get("input_schema").is_some()
                    || item.fields.get("content").is_some() =>
            {
                &["Overview"]
            }
            Workspace::Apps => &["Overview", "Skills"],
            _ => &["Overview"],
        };
        let total = tabs.iter().map(|s| s.len() as u16 + 6).sum::<u16>();
        let mut x = area.x + area.width.saturating_sub(total) / 2;
        for (i, label) in tabs.iter().enumerate() {
            let width = (label.len() as u16 + 6).min(area.right().saturating_sub(x));
            self.button(
                frame,
                Rect::new(x, area.y + 4, width, 1),
                &format!(" {} {} ", i + 1, label),
                HitAction::DetailTab(i),
                self.detail_tab == i,
            );
            x += width;
        }
        let body = Rect::new(
            area.x,
            area.y + 6,
            area.width,
            area.height.saturating_sub(6),
        );
        let mut rows = vec![];
        match (self.workspace, self.detail_tab) {
            (Workspace::Projects, 1) => {
                rows.push(markdown::styled("Files", Style::default().fg(TEXT).bold()));
                for file in field_list(&item, "files") {
                    let name = text_field(file, "name");
                    let path = text_field(file, "path");
                    let id = file
                        .get("embedId")
                        .or_else(|| file.get("embed_id"))
                        .or_else(|| file.get("target_id"))
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    rows.push(vec![markdown::Part {
                        text: format!(
                            "{} {}",
                            if text_field(file, "kind") == "folder" {
                                "▸"
                            } else {
                                "▤"
                            },
                            if path.is_empty() { name } else { path }
                        ),
                        style: Style::default().fg(TEXT),
                        link: if id.is_empty() {
                            None
                        } else {
                            Some(Link::ProjectFile {
                                project: item.id.clone(),
                                embed: id.into(),
                                name: if path.is_empty() { name } else { path }.into(),
                            })
                        },
                    }]);
                }
                if field_list(&item, "files").is_empty() {
                    rows.push(markdown::plain(
                        "No files available. Refresh to synchronize this Project.",
                    ));
                }
            }
            (Workspace::Projects, 2) => {
                let tasks = self.items[4]
                    .iter()
                    .filter(|task| text_field(&task.fields, "project_id") == item.id)
                    .cloned()
                    .collect::<Vec<_>>();
                if tasks.is_empty() {
                    for task in field_list(&item, "tasks") {
                        rows.push(markdown::styled(
                            format!(
                                "● {} · {}",
                                text_field(task, "title"),
                                text_field(task, "status")
                            ),
                            Style::default().fg(task_color(text_field(task, "status"))),
                        ));
                    }
                    if field_list(&item, "tasks").is_empty() {
                        rows.push(markdown::plain("No Tasks in this Project"));
                    }
                }
                for task in tasks {
                    rows.push(markdown::styled(
                        format!("● {} · {}", task.title, task.status.replace('_', " ")),
                        Style::default().fg(task_color(&task.status)),
                    ));
                }
            }
            (Workspace::Workflows, 0) => {
                if body.height > 1 {
                    self.button(
                        frame,
                        Rect::new(body.x, body.y, 14.min(body.width), 1),
                        "▶ Run now",
                        HitAction::Run,
                        false,
                    );
                    if body.width > 24 {
                        self.button(
                            frame,
                            Rect::new(body.x + 15, body.y, 12, 1),
                            if item
                                .fields
                                .get("enabled")
                                .and_then(Value::as_bool)
                                .unwrap_or(false)
                            {
                                "◉ Enabled"
                            } else {
                                "○ Paused"
                            },
                            HitAction::Toggle,
                            false,
                        );
                    }
                }
                rows.push(vec![]);
                rows.push(vec![]);
                let nodes = field_list(&item, "nodes");
                let nodes = if nodes.is_empty() {
                    item.fields
                        .pointer("/graph/nodes")
                        .and_then(Value::as_array)
                        .map(Vec::as_slice)
                        .unwrap_or(&[])
                } else {
                    nodes
                };
                for (i, node) in nodes.iter().enumerate() {
                    let id = text_field(node, "id");
                    let title = text_field(node, "title");
                    let kind = text_field(node, "type");
                    let focused = i == self.node_selected;
                    rows.push(markdown::styled(
                        format!(
                            "{}╭─ {} ─╮",
                            if focused { "▸ " } else { "  " },
                            if title.is_empty() { kind } else { title }
                        ),
                        Style::default()
                            .fg(if focused { ACCENT } else { BLUE })
                            .bold(),
                    ));
                    if let Some(part) = rows.last_mut().and_then(|row| row.first_mut()) {
                        part.link = Some(Link::Node(i));
                    }
                    rows.push(markdown::plain(format!("  │ {kind} · {id}")));
                    if let Some(config) = node.get("config").and_then(Value::as_object) {
                        for (key, value) in config {
                            if value.is_string() || value.is_number() || value.is_boolean() {
                                rows.push(markdown::plain(format!(
                                    "  │ {}: {}",
                                    key.replace('_', " "),
                                    value
                                        .as_str()
                                        .map(str::to_owned)
                                        .unwrap_or_else(|| value.to_string())
                                )));
                            }
                        }
                    }
                    rows.push(markdown::styled(
                        "  ╰─────────────╯",
                        Style::default().fg(BLUE),
                    ));
                    let edges = item
                        .fields
                        .get("edges")
                        .or_else(|| item.fields.pointer("/graph/edges"))
                        .and_then(Value::as_array);
                    let targets = edges
                        .into_iter()
                        .flatten()
                        .filter(|e| text_field(e, "source") == id || text_field(e, "from") == id)
                        .map(|e| {
                            let target = text_field(e, "target");
                            if target.is_empty() {
                                text_field(e, "to")
                            } else {
                                target
                            }
                        })
                        .collect::<Vec<_>>();
                    if !targets.is_empty() {
                        rows.push(markdown::styled(
                            format!("       ↓ {}", targets.join(" · ")),
                            Style::default().fg(MUTED),
                        ));
                    } else if i + 1 < nodes.len() {
                        rows.push(markdown::styled("       ↓", Style::default().fg(MUTED)));
                    }
                }
                if nodes.is_empty() {
                    rows.push(markdown::plain("No workflow steps available"));
                }
            }
            (Workspace::Workflows, 1) => {
                for run in field_list(&item, "runs") {
                    rows.push(markdown::styled(
                        format!(
                            "● {} · {}",
                            text_field(run, "status"),
                            text_field(run, "id")
                        ),
                        Style::default().fg(task_color(text_field(run, "status"))),
                    ));
                    if let Some(part) = rows.last_mut().and_then(|row| row.first_mut()) {
                        part.link = Some(Link::Run(run.clone()));
                    }
                    if let Some(steps) = run.get("node_runs").and_then(Value::as_array) {
                        for step in steps {
                            rows.push(markdown::plain(format!(
                                "  {} · {}",
                                text_field(step, "node_id"),
                                text_field(step, "status")
                            )));
                        }
                    }
                }
                if field_list(&item, "runs").is_empty() {
                    rows.push(markdown::plain("No runs available"));
                }
            }
            (Workspace::Tasks, 1) => {
                for activity in field_list(&item, "activity") {
                    rows.push(markdown::plain(format!(
                        "{} {}",
                        text_field(activity, "created_at"),
                        text_field(activity, "text")
                    )));
                }
                if field_list(&item, "activity").is_empty() {
                    rows.push(markdown::plain("No activity yet"));
                }
            }
            (Workspace::Apps, 0) if item.fields.get("input_schema").is_some() => {
                rows.extend(markdown::render(&item.description, body.width as usize));
                rows.push(vec![]);
                if item.fields["execution_available"] == true {
                    rows.push(markdown::styled(
                        "Use skill · Enter opens typed inputs and a confirmation",
                        Style::default().fg(ACCENT).bold(),
                    ));
                } else {
                    rows.push(markdown::plain(
                        item.fields["unavailable_reason"]
                            .as_str()
                            .unwrap_or("This skill cannot run here"),
                    ));
                }
                if let Some(cost) = item.fields.pointer("/pricing/fixed") {
                    rows.push(markdown::plain(format!("{cost} credits per request")));
                }
                rows.push(markdown::plain("Only declared skill inputs are submitted. Unknown schema types are unavailable."));
            }
            (Workspace::Apps, 0)
                if item.id.starts_with("embed:") || item.fields.get("content").is_some() =>
            {
                let results = apps::result_rows(&item, body.width as usize);
                if results.is_empty() {
                    rows.extend(markdown::render(&embed_content(&item), body.width as usize));
                } else {
                    rows.extend(results);
                }
            }
            (Workspace::Apps, 1) => {
                for skill in field_list(&item, "skills") {
                    rows.push(markdown::styled(
                        text_field(skill, "name"),
                        Style::default().fg(app_color(&item.category)).bold(),
                    ));
                    if let Some(id) = skill["id"].as_str().or_else(|| skill.as_str())
                        && let Some(part) = rows.last_mut().and_then(|r| r.first_mut())
                    {
                        part.link = Some(Link::Skill {
                            app: item.id.clone(),
                            skill: id.into(),
                        });
                    }
                    rows.extend(markdown::render(
                        text_field(skill, "description"),
                        body.width as usize,
                    ));
                }
            }
            _ => {
                if !item.status.is_empty() {
                    rows.push(markdown::styled(
                        format!("● {}", item.status.replace('_', " ")),
                        Style::default().fg(task_color(&item.status)),
                    ));
                    rows.push(vec![]);
                }
                rows.extend(markdown::render(&item.description, body.width as usize));
                let readme = text_field(&item.fields, "readme");
                if !readme.is_empty() {
                    rows.push(vec![]);
                    rows.extend(markdown::render(readme, body.width as usize));
                }
                if let Some(fields) = item.fields.as_object() {
                    for (key, value) in fields {
                        if matches!(key.as_str(), "description" | "readme" | "title" | "content") {
                            continue;
                        }
                        if let Some(text) = value.as_str()
                            && !text.is_empty()
                        {
                            rows.push(markdown::plain(format!(
                                "{}: {}",
                                key.replace('_', " "),
                                text
                            )));
                        }
                    }
                }
            }
        }
        self.detail_links.clear();
        for part in rows.iter().flatten() {
            if let Some(link) = &part.link
                && !self.detail_links.contains(link)
            {
                self.detail_links.push(link.clone());
            }
        }
        let rows = rows
            .into_iter()
            .flat_map(|row| markdown::wrap(row, body.width as usize))
            .collect::<Vec<_>>();
        self.paint_rows(frame, body, &rows, false);
        // Buttons on the graph's first row must remain above text scroll hit targets.
        if self.workspace == Workspace::Workflows
            && self.detail_tab == 0
            && self.scroll == 0
            && body.height > 0
        {
            self.hit(
                Rect::new(body.x, body.y, 14.min(body.width), 1),
                HitAction::Run,
            );
            if body.width > 26 {
                self.hit(Rect::new(body.x + 15, body.y, 12, 1), HitAction::Toggle);
            }
        }
    }
    fn settings_pages(&self) -> Vec<(String, String, bool)> {
        let route = self
            .settings
            .as_ref()
            .map(|s| s.route.as_str())
            .unwrap_or("");
        let dynamic = self.items[5]
            .iter()
            .filter(|item| {
                let parent = text_field(&item.fields, "parent");
                parent == route && item.id != route
            })
            .map(|item| {
                (
                    item.id.clone(),
                    item.title.clone(),
                    item.fields
                        .get("browser_only")
                        .and_then(Value::as_bool)
                        .unwrap_or(false),
                )
            })
            .collect::<Vec<_>>();
        if !dynamic.is_empty() {
            return dynamic;
        }
        let entries: &[(&str, &str)] = match route {
            "" => &[
                ("profile", "Profile"),
                ("account", "Account"),
                ("interface", "Interface"),
                ("notifications", "Notifications"),
                ("privacy", "Privacy"),
                ("settings_memories", "Memories"),
                ("mates", "Mates"),
                ("apps", "Apps"),
                ("projects", "Projects"),
                ("teams", "Teams"),
                ("billing", "Billing"),
                ("developers", "Developers"),
                ("newsletter", "Newsletter"),
                ("support", "Support"),
            ],
            "account" => &[
                ("account/username", "Username"),
                ("account/email", "Email"),
                ("account/security", "Security"),
                ("account/export", "Export account"),
                ("account/import", "Import account"),
                ("account/delete", "Delete account"),
            ],
            "account/security" => &[
                ("account/security/passkeys", "Passkeys"),
                ("account/security/password", "Password"),
                ("account/security/2fa", "Two-factor authentication"),
                ("account/security/sessions", "Sessions"),
            ],
            "interface" => &[
                ("interface/language", "Language"),
                ("interface/appearance", "Appearance (web app)"),
            ],
            "notifications" => &[("notifications/chat", "Email notifications")],
            "privacy" => &[
                ("privacy/hide-personal-data", "Personal data"),
                ("privacy/debug", "Debug sessions"),
            ],
            "settings_memories" => &[("settings_memories/list", "Saved Memories")],
            "teams" => &[
                ("teams/context", "Active Team"),
                ("teams/members", "Team members"),
            ],
            "billing" => &[
                ("billing/overview", "Overview"),
                ("billing/usage", "Usage"),
                ("billing/invoices", "Invoices"),
                ("billing/buy-credits", "Buy credits"),
                ("billing/gift-cards", "Gift cards"),
            ],
            "developers" => &[
                ("developers/api-keys", "API keys"),
                ("developers/devices", "Devices"),
                ("developers/webhooks", "Webhooks"),
            ],
            "newsletter" => &[
                ("newsletter/categories", "Categories"),
                ("newsletter/subscribe", "Subscribe"),
            ],
            "support" => &[("support/help", "Help center")],
            _ => &[],
        };
        entries
            .iter()
            .map(|(id, title)| (id.to_string(), title.to_string(), browser_only(id)))
            .collect()
    }
    fn settings_key(&mut self, key: KeyEvent) -> Vec<UiCommand> {
        let pages = self.settings_pages();
        let settings = self.settings.as_mut().unwrap();
        match key.code {
            KeyCode::Up => settings.selected = settings.selected.saturating_sub(1),
            KeyCode::Down => {
                settings.selected = (settings.selected + 1).min(pages.len().saturating_sub(1))
            }
            KeyCode::Enter => {
                if let Some((route, _, _)) = pages.get(settings.selected) {
                    let route = route.clone();
                    return self.activate(HitAction::SettingsRoute(route));
                } else {
                    self.settings_form();
                }
            }
            KeyCode::Char('e') => self.settings_form(),
            _ => {}
        }
        vec![]
    }
    fn draw_settings(&mut self, frame: &mut Frame, area: Rect) {
        let route = self
            .settings
            .as_ref()
            .map(|s| s.route.clone())
            .unwrap_or_default();
        let selected = self.settings.as_ref().map(|s| s.selected).unwrap_or(0);
        frame.render_widget(panel(" Settings ", true), area);
        let inner = inset(area, 1, 1);
        if inner.height < 3 {
            return;
        }
        self.button(
            frame,
            Rect::new(inner.x, inner.y, 7.min(inner.width), 1),
            "‹ Back",
            HitAction::Back,
            false,
        );
        if inner.width > 14 {
            self.button(
                frame,
                Rect::new(inner.right() - 7, inner.y, 7, 1),
                "Close",
                HitAction::Close,
                false,
            );
        }
        let title = if route.is_empty() {
            if self.authenticated {
                format!("{} · Account settings", self.username)
            } else {
                "Settings".into()
            }
        } else {
            route
                .split('/')
                .map(|s| s.replace('_', " "))
                .collect::<Vec<_>>()
                .join(" › ")
        };
        frame.render_widget(
            Paragraph::new(title)
                .style(Style::default().fg(BLUE).bold())
                .wrap(Wrap { trim: false }),
            Rect::new(inner.x, inner.y + 2, inner.width, 2.min(inner.height - 2)),
        );
        let pages = self.settings_pages();
        let start_y = inner.y + 5;
        let visible = inner.bottom().saturating_sub(start_y + 2) as usize;
        let offset = selected.saturating_sub(visible.saturating_sub(1));
        if !pages.is_empty() {
            for (row, (i, (id, title, web))) in pages
                .iter()
                .enumerate()
                .skip(offset)
                .take(visible)
                .enumerate()
            {
                self.button(
                    frame,
                    Rect::new(inner.x, start_y + row as u16, inner.width, 1),
                    &format!(
                        "{} {}{}",
                        if i == selected { "›" } else { " " },
                        title,
                        if *web { " ↗" } else { "" }
                    ),
                    HitAction::SettingsRoute(id.clone()),
                    i == selected,
                );
            }
        } else {
            let body = Rect::new(
                inner.x,
                start_y,
                inner.width,
                inner.bottom().saturating_sub(start_y + 3),
            );
            let item = self.items[5].iter().find(|i| i.id == route).cloned();
            if browser_only(&route) {
                frame.render_widget(Paragraph::new("This operation requires browser verification. Open the web app to continue.").wrap(Wrap{trim:false}).style(Style::default().fg(MUTED)),body);
                let url = format!("https://openmates.org/#settings/{}", route);
                self.button(
                    frame,
                    Rect::new(inner.x, inner.bottom().saturating_sub(3), inner.width, 1),
                    "Open in browser ↗",
                    HitAction::Link(Link::Url(url)),
                    false,
                );
            } else if let Some(item) = item {
                let mut rows = markdown::render(&item.description, body.width as usize);
                if let Some(values) = item.fields.get("values").and_then(Value::as_object) {
                    for (key, value) in values {
                        if !sensitive_key(key) {
                            rows.push(markdown::plain(format!(
                                "{}: {}",
                                key.replace('_', " "),
                                display_value(value)
                            )));
                        }
                    }
                }
                self.paint_rows(frame, body, &rows, false);
                if item
                    .fields
                    .get("fields")
                    .and_then(Value::as_array)
                    .is_some_and(|f| !f.is_empty())
                {
                    self.button(
                        frame,
                        Rect::new(inner.x, inner.bottom().saturating_sub(3), inner.width, 1),
                        "Edit settings · e",
                        HitAction::SettingsEdit,
                        false,
                    );
                }
            } else {
                frame.render_widget(Paragraph::new("Settings data unavailable. Refresh to retry, or open this page in the web app.").style(Style::default().fg(MUTED)).wrap(Wrap{trim:false}),body);
                self.button(
                    frame,
                    Rect::new(inner.x, inner.bottom().saturating_sub(3), inner.width, 1),
                    "Open in browser ↗",
                    HitAction::Link(Link::Url(format!(
                        "https://openmates.org/#settings/{route}"
                    ))),
                    false,
                );
            }
        }
        if inner.height > 4 && route.is_empty() {
            let y = inner.bottom() - 1;
            if self.authenticated {
                self.button(
                    frame,
                    Rect::new(inner.x, y, inner.width, 1),
                    "Sign out",
                    HitAction::Logout,
                    false,
                );
            } else {
                let width = inner.width / 2;
                self.button(
                    frame,
                    Rect::new(inner.x, y, width, 1),
                    "Sign in",
                    HitAction::Login,
                    false,
                );
                self.button(
                    frame,
                    Rect::new(inner.x + width, y, width, 1),
                    "Pair terminal",
                    HitAction::Pair,
                    false,
                );
            }
        }
    }
    fn settings_form(&mut self) {
        let Some(settings) = &self.settings else {
            return;
        };
        let route = settings.route.clone();
        let Some(item) = self.items[5].iter().find(|i| i.id == route) else {
            return;
        };
        let mut fields = vec![];
        for schema in field_list(item, "fields") {
            let key = text_field(schema, "key");
            if key.is_empty() || sensitive_key(key) {
                continue;
            }
            let label = text_field(schema, "label");
            let value = item
                .fields
                .get("values")
                .and_then(|v| v.get(key))
                .unwrap_or(&Value::Null);
            let mut field = Field::text(
                key,
                if label.is_empty() { key } else { label },
                &display_value(value),
                schema
                    .get("required")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
            );
            field.kind = match text_field(schema, "type") {
                "boolean" => FieldKind::Bool,
                "number" => FieldKind::Number,
                "choice" => FieldKind::Choice(
                    schema
                        .get("options")
                        .and_then(Value::as_array)
                        .map(|options| {
                            options
                                .iter()
                                .filter_map(Value::as_str)
                                .map(str::to_owned)
                                .collect()
                        })
                        .unwrap_or_default(),
                ),
                "multiline" => FieldKind::Multiline,
                _ => FieldKind::Text,
            };
            fields.push(field);
        }
        if !fields.is_empty() {
            self.form = Some(Form::new(&item.title, FormPurpose::Settings(route), fields));
        }
    }
    fn draw_form(&mut self, frame: &mut Frame, screen: Rect) {
        if self
            .form
            .as_ref()
            .is_some_and(|f| matches!(f.purpose, FormPurpose::AppConfirm { .. }))
        {
            self.draw_app_confirmation(frame, screen);
            return;
        }

        if self
            .form
            .as_ref()
            .is_some_and(|f| matches!(f.purpose, FormPurpose::Consent { .. }))
        {
            self.draw_consent(frame, screen);
            return;
        }

        if self
            .form
            .as_ref()
            .is_some_and(|f| matches!(f.purpose, FormPurpose::ShareResult { .. }))
        {
            self.draw_share_result(frame, screen);
            return;
        }
        let palette = self
            .form
            .as_ref()
            .is_some_and(|f| matches!(f.purpose, FormPurpose::Palette));
        if palette {
            self.draw_palette(frame, screen);
            return;
        }
        let form = self.form.as_ref().unwrap();
        let help = matches!(form.purpose, FormPurpose::Help);
        let pairing = matches!(form.purpose, FormPurpose::Pairing);
        let height = if help {
            22
        } else if pairing {
            30
        } else {
            (form.fields.len() as u16 * 4 + 7).clamp(11, 32)
        };
        let area = center(screen, 76, height);
        frame.render_widget(Clear, area);
        frame.render_widget(panel(format!(" {} ", form.title), true), area);
        let inner = inset(area, 2, 1);
        if inner.height < 3 {
            return;
        }
        if help {
            let source = if let Some(field) = form.fields.first() {
                field.editor.text.to_string()
            } else {
                "# OpenMates keyboard shortcuts\n\nCtrl+1…5 · Chats, Apps, Projects, Workflows, Tasks\nCtrl+6 / Ctrl+S · Settings\nCtrl+B · Toggle recent-chat sidebar\nCtrl+G · Focus workspace navigation · ←/→ · Enter · Escape\nCtrl+P / Ctrl+K · Search available actions\nTab / Shift+Tab · Move between composer, sidebar and content\n←/→ · Select cards · Enter opens\nn / e / d · Create, edit, delete selected item\n1 / 2 / 3 · Switch detail tabs\nPageUp / PageDown / mouse wheel · Scroll\nAlt+Enter or Shift+Enter · Composer newline\nHome / End / arrows / Delete · Edit at cursor\nCtrl+Y · Release mouse capture for terminal text selection\nCtrl+C · Stop response, or exit when idle\nEscape · Back, dismiss dialog, close settings\n\nAll layouts, editing, Markdown, encryption and networking run in Rust.".into()
            };
            let rows = markdown::render(&source, inner.width as usize);
            let saved = self.scroll;
            self.scroll = form.scroll;
            self.paint_rows(
                frame,
                Rect::new(
                    inner.x,
                    inner.y,
                    inner.width,
                    inner.height.saturating_sub(2),
                ),
                &rows,
                false,
            );
            if let Some(form) = self.form.as_mut() {
                form.scroll = self.scroll;
            }
            self.scroll = saved;
            self.button(
                frame,
                Rect::new(inner.x, inner.bottom() - 1, inner.width, 1),
                "Close · Enter / Escape",
                HitAction::FormCancel,
                false,
            );
            return;
        }
        if pairing {
            let uri = form
                .fields
                .first()
                .map(|f| f.editor.text.to_string())
                .unwrap_or_default();
            let mut lines = vec![
                Line::from("Open the signed-in web app and approve this terminal."),
                Line::default(),
            ];
            if let Ok(code) = qrcode::QrCode::new(uri.as_bytes()) {
                let side = code.width();
                if (side + 4) as u16 <= inner.width && (side.div_ceil(2) + 5) as u16 <= inner.height
                {
                    let dark = |x: isize, y: isize| -> bool {
                        x >= 0
                            && y >= 0
                            && (x as usize) < side
                            && (y as usize) < side
                            && code[(x as usize, y as usize)] == qrcode::Color::Dark
                    };
                    for y in (-2..side as isize + 2).step_by(2) {
                        let mut line = String::new();
                        for x in -2..side as isize + 2 {
                            line.push(match (dark(x, y), dark(x, y + 1)) {
                                (true, true) => '█',
                                (true, false) => '▀',
                                (false, true) => '▄',
                                _ => ' ',
                            });
                        }
                        lines.push(Line::from(Span::styled(
                            line,
                            Style::default().fg(Color::Black).bg(Color::White),
                        )));
                    }
                }
            }
            lines.push(Line::default());
            lines.push(Line::from(markdown::clean(&uri)));
            frame.render_widget(
                Paragraph::new(lines).wrap(Wrap { trim: false }),
                Rect::new(
                    inner.x,
                    inner.y,
                    inner.width,
                    inner.height.saturating_sub(2),
                ),
            );
            self.button(
                frame,
                Rect::new(inner.x, inner.bottom() - 1, inner.width, 1),
                "Enter PIN · Enter / Cancel · Escape",
                HitAction::FormSubmit,
                false,
            );
            return;
        }
        let field_count = form.fields.len();
        let available = inner.height.saturating_sub(4);
        let selected = form.selected;
        let mut offset = selected.min(field_count.saturating_sub(1));
        let field_height = |index: usize| {
            if form
                .fields
                .get(index)
                .is_some_and(|f| matches!(f.kind, FieldKind::Multiline))
            {
                6
            } else {
                4
            }
        };
        let mut used = field_height(offset);
        while offset > 0 && used + field_height(offset - 1) <= available as usize {
            offset -= 1;
            used += field_height(offset);
        }
        let title = form.title.clone();
        let _ = title;
        let mut y = inner.y;
        let mut field_hits = vec![];
        let mut cursor_position = None;
        for (i, field) in form.fields.iter().enumerate().skip(offset) {
            let multiline = matches!(field.kind, FieldKind::Multiline);
            let h = if multiline { 5 } else { 3 };
            if y + h > inner.bottom().saturating_sub(3) {
                break;
            }
            let active = selected == i;
            let label = format!("{}{}", field.label, if field.required { " *" } else { "" });
            frame.render_widget(
                Paragraph::new(markdown::clean(&label)).style(Style::default().fg(if active {
                    ACCENT
                } else {
                    MUTED
                })),
                Rect::new(inner.x, y, inner.width, 1),
            );
            let rect = Rect::new(inner.x, y + 1, inner.width, h - 1);
            let value_area = inset(rect, 1, 0);
            frame.render_widget(
                Block::default().style(Style::default().bg(if active { BORDER } else { PANEL })),
                rect,
            );
            let (rows, (col, row)) = field.editor.display(
                value_area.width as usize,
                matches!(field.kind, FieldKind::Secret),
            );
            let row_offset = row.saturating_sub(value_area.height.saturating_sub(1) as usize);
            let value = match &field.kind {
                FieldKind::Bool => vec![if field.editor.text.as_str() == "true" {
                    "[✓] Enabled · Space to change".into()
                } else {
                    "[ ] Disabled · Space to change".into()
                }],
                FieldKind::Choice(_) => vec![format!("‹ {} ›", field.editor.text.as_str())],
                _ => rows
                    .into_iter()
                    .skip(row_offset)
                    .take(value_area.height as usize)
                    .collect(),
            };
            frame.render_widget(
                Paragraph::new(value.into_iter().map(Line::from).collect::<Vec<_>>())
                    .style(Style::default().fg(TEXT)),
                value_area,
            );
            if active
                && !matches!(field.kind, FieldKind::Choice(_) | FieldKind::Bool)
                && value_area.width > 0
                && value_area.height > 0
            {
                cursor_position = Some((
                    value_area.x + (col as u16).min(value_area.width - 1),
                    value_area.y
                        + (row.saturating_sub(row_offset) as u16).min(value_area.height - 1),
                ));
            }
            field_hits.push((rect, HitAction::FormField(i)));
            y += h + 1;
        }
        let form = self.form.as_ref().unwrap();
        let error = form.error.clone();
        let busy = form.busy;
        let destructive = matches!(form.purpose, FormPurpose::Delete(..));
        let sharing = matches!(form.purpose, FormPurpose::Share(..));
        let auth = matches!(form.purpose, FormPurpose::Login);
        if !error.is_empty() {
            frame.render_widget(
                Paragraph::new(error)
                    .style(Style::default().fg(ACCENT))
                    .wrap(Wrap { trim: false }),
                Rect::new(inner.x, inner.bottom().saturating_sub(3), inner.width, 2),
            );
        }
        for (rect, action) in field_hits {
            self.hit(rect, action);
        }
        let button_width = inner.width.min(26);
        self.button(
            frame,
            Rect::new(inner.x, inner.bottom() - 1, button_width, 1),
            if busy {
                "Submitting…"
            } else if sharing {
                "Generate Link · Ctrl+Enter"
            } else if destructive {
                "Delete permanently · Ctrl+Enter"
            } else {
                "Submit · Ctrl+Enter"
            },
            HitAction::FormSubmit,
            selected == field_count,
        );
        if auth && inner.width > 40 {
            self.button(
                frame,
                Rect::new(inner.right() - 22, inner.bottom() - 1, 22, 1),
                "Pair instead ↗",
                HitAction::Pair,
                false,
            );
        } else if inner.width > 32 {
            self.button(
                frame,
                Rect::new(inner.right() - 16, inner.bottom() - 1, 16, 1),
                "Cancel · Escape",
                HitAction::FormCancel,
                false,
            );
        }
        if let Some(position) = cursor_position {
            frame.set_cursor_position(position);
        }
    }
    fn draw_app_confirmation(&mut self, frame: &mut Frame, screen: Rect) {
        let area = center(screen, 84, 32);
        frame.render_widget(Clear, area);
        frame.render_widget(panel(" Confirm app skill execution ", true), area);
        let inner = inset(area, 2, 1);
        if inner.height < 7 {
            return;
        }
        let form = self.form.as_ref().unwrap();
        let FormPurpose::AppConfirm { skill, input, .. } = &form.purpose else {
            return;
        };
        let source = apps::summary(skill, input);
        let rows = markdown::render(&source, inner.width as usize);
        let form_scroll = form.scroll;
        let error = form.error.clone();
        let busy = form.busy;
        let confirmation = form.fields[0].editor.text.to_string();
        let y = inner.bottom() - 5;
        let saved = self.scroll;
        self.scroll = form_scroll;
        self.paint_rows(
            frame,
            Rect::new(inner.x, inner.y, inner.width, inner.height - 6),
            &rows,
            false,
        );
        if let Some(form) = self.form.as_mut() {
            form.scroll = self.scroll;
        }
        self.scroll = saved;
        frame.render_widget(
            Paragraph::new("Type RUN to execute and accept the credit charge")
                .style(Style::default().fg(ACCENT)),
            Rect::new(inner.x, y, inner.width, 1),
        );
        frame.render_widget(
            Paragraph::new(format!("› {confirmation}")).style(Style::default().fg(TEXT).bg(BORDER)),
            Rect::new(inner.x, y + 1, inner.width, 1),
        );
        self.hit(
            Rect::new(inner.x, y + 1, inner.width, 1),
            HitAction::FormField(0),
        );
        if !error.is_empty() {
            frame.render_widget(
                Paragraph::new(error).style(Style::default().fg(ACCENT)),
                Rect::new(inner.x, y + 2, inner.width, 1),
            );
        }
        let half = inner.width / 2;
        self.button(
            frame,
            Rect::new(inner.x, inner.bottom() - 1, half, 1),
            if busy {
                "Running…"
            } else {
                "Run skill · Ctrl+Enter"
            },
            HitAction::FormSubmit,
            false,
        );
        self.button(
            frame,
            Rect::new(inner.x + half, inner.bottom() - 1, inner.width - half, 1),
            "Back to inputs · Escape",
            HitAction::FormCancel,
            false,
        );
        if !busy {
            frame.set_cursor_position((
                inner.x + (confirmation.width() as u16 + 2).min(inner.width - 1),
                y + 1,
            ));
        }
    }
    fn draw_consent(&mut self, frame: &mut Frame, screen: Rect) {
        let area = center(screen, 88, 32);
        frame.render_widget(Clear, area);
        let sub_chats=self.form.as_ref().is_some_and(|form|matches!(&form.purpose,FormPurpose::Consent{items,..}if items.iter().any(|item|item.fields["consent_kind"]=="sub_chats")));
        frame.render_widget(
            panel(
                if sub_chats {
                    " Start these sub-chats? "
                } else {
                    " Review requested Memories "
                },
                true,
            ),
            area,
        );
        let inner = inset(area, 2, 1);
        if inner.height < 4 {
            return;
        }
        let Some(form) = self.form.as_ref() else {
            return;
        };
        let FormPurpose::Consent { items, .. } = &form.purpose else {
            return;
        };
        let selected = form.selected;
        let item_count = items.len();
        let available = inner.height.saturating_sub(6) as usize;
        let mut lines = vec![
            Line::from(if sub_chats {
                "Choose which proposed sub-chats to start."
            } else {
                "Choose which categories to share with this response."
            }),
            Line::from("Space changes selection · Ctrl+Enter approves · Escape denies all"),
            Line::default(),
        ];
        if let Some(context) = &form.context {
            lines.insert(
                0,
                Line::from(Span::styled(
                    format!("Requested by: {context}"),
                    Style::default().fg(BLUE).bold(),
                )),
            );
        }
        let mut actions = vec![];
        let mut remaining = available;
        let start = selected
            .min(items.len().saturating_sub(1))
            .saturating_sub(1);
        for (i, item) in items.iter().enumerate().skip(start) {
            if remaining == 0 {
                break;
            }
            let approved = form
                .fields
                .get(i)
                .is_some_and(|f| f.editor.text.as_str() == "true");
            let label = format!(
                "{} [{}] {} · {}",
                if i == selected { "›" } else { " " },
                if approved { "✓" } else { " " },
                item.title,
                item.description
            );
            let y = inner.y + lines.len() as u16;
            lines.push(Line::from(Span::styled(
                markdown::clean(&label),
                Style::default()
                    .fg(if i == selected { ACCENT } else { TEXT })
                    .bold(),
            )));
            actions.push((
                Rect::new(inner.x, y, inner.width, 1),
                HitAction::FormField(i),
            ));
            remaining -= 1;
            if i == selected
                && let Some(entries) = item.fields.get("entries")
            {
                for row in markdown::render(
                    &display_value(entries),
                    inner.width.saturating_sub(2) as usize,
                )
                .into_iter()
                .take(remaining.min(8))
                {
                    lines.push(Line::from(
                        row.into_iter()
                            .map(|part| Span::styled(format!("  {}", part.text), part.style))
                            .collect::<Vec<_>>(),
                    ));
                    remaining -= 1;
                }
            }
        }
        frame.render_widget(
            Paragraph::new(lines),
            Rect::new(
                inner.x,
                inner.y,
                inner.width,
                inner.height.saturating_sub(2),
            ),
        );
        for (rect, action) in actions {
            self.hit(rect, action);
        }
        let half = inner.width / 2;
        self.button(
            frame,
            Rect::new(inner.x, inner.bottom() - 1, half, 1),
            if sub_chats {
                "Start selected · Ctrl+Enter"
            } else {
                "Share selected · Ctrl+Enter"
            },
            HitAction::FormSubmit,
            selected == item_count,
        );
        self.button(
            frame,
            Rect::new(inner.x + half, inner.bottom() - 1, inner.width - half, 1),
            "Deny all · Escape",
            HitAction::DenyConsent,
            false,
        );
    }
    fn draw_share_result(&mut self, frame: &mut Frame, screen: Rect) {
        let area = center(screen, 80, 34);
        frame.render_widget(Clear, area);
        frame.render_widget(panel(" Private share link ", true), area);
        let inner = inset(area, 2, 1);
        if inner.height < 5 {
            return;
        }
        let Some(form) = &self.form else {
            return;
        };
        let FormPurpose::ShareResult { visible, qr } = form.purpose else {
            return;
        };
        let url = form
            .fields
            .first()
            .map(|f| f.editor.text.as_str())
            .unwrap_or("");
        let mut lines = vec![
            Line::from("Share only with intended recipients. The URL contains a private key."),
            Line::default(),
        ];
        if visible {
            lines.push(Line::from(markdown::clean(url)));
        } else {
            lines.push(Line::from("URL hidden · u shows the URL"));
        }
        if qr && let Ok(code) = qrcode::QrCode::new(url.as_bytes()) {
            let side = code.width();
            if side + 4 <= inner.width as usize {
                let dark = |x: isize, y: isize| {
                    x >= 0
                        && y >= 0
                        && (x as usize) < side
                        && (y as usize) < side
                        && code[(x as usize, y as usize)] == qrcode::Color::Dark
                };
                for y in (-2..side as isize + 2).step_by(2) {
                    let mut line = String::new();
                    for x in -2..side as isize + 2 {
                        line.push(match (dark(x, y), dark(x, y + 1)) {
                            (true, true) => '█',
                            (true, false) => '▀',
                            (false, true) => '▄',
                            _ => ' ',
                        });
                    }
                    lines.push(Line::from(Span::styled(
                        line,
                        Style::default().fg(Color::Black).bg(Color::White),
                    )));
                }
            } else {
                lines.push(Line::from("Resize wider to show the QR code"));
            }
        }
        frame.render_widget(
            Paragraph::new(lines)
                .wrap(Wrap { trim: false })
                .style(Style::default().fg(TEXT)),
            Rect::new(
                inner.x,
                inner.y,
                inner.width,
                inner.height.saturating_sub(2),
            ),
        );
        let third = inner.width / 3;
        self.button(
            frame,
            Rect::new(inner.x, inner.bottom() - 1, third, 1),
            "Copy · c",
            HitAction::CopyShare,
            false,
        );
        self.button(
            frame,
            Rect::new(inner.x + third, inner.bottom() - 1, third, 1),
            if visible {
                "Hide URL · u"
            } else {
                "Show URL · u"
            },
            HitAction::RevealShare,
            visible,
        );
        self.button(
            frame,
            Rect::new(
                inner.x + third * 2,
                inner.bottom() - 1,
                inner.width - third * 2,
                1,
            ),
            "Show QR · q",
            HitAction::QrShare,
            qr,
        );
    }
    fn draw_palette(&mut self, frame: &mut Frame, screen: Rect) {
        let area = center(screen, 68, 23);
        frame.render_widget(Clear, area);
        frame.render_widget(panel(" Actions · Escape closes ", true), area);
        let inner = inset(area, 2, 1);
        if inner.height < 3 {
            return;
        }
        frame.render_widget(
            Paragraph::new(format!("› {}", self.palette_query.text.as_str()))
                .style(Style::default().fg(TEXT)),
            Rect::new(inner.x, inner.y, inner.width, 1),
        );
        let actions = self.palette_actions();
        let selected = self
            .form
            .as_ref()
            .map(|f| f.selected)
            .unwrap_or(0)
            .min(actions.len().saturating_sub(1));
        if let Some(form) = self.form.as_mut() {
            form.selected = selected;
        }
        let visible = inner.height.saturating_sub(2) as usize;
        let start = selected.saturating_sub(visible.saturating_sub(1));
        for (row, (i, (label, command))) in actions
            .iter()
            .enumerate()
            .skip(start)
            .take(visible)
            .enumerate()
        {
            self.button(
                frame,
                Rect::new(inner.x, inner.y + 2 + row as u16, inner.width, 1),
                &format!(
                    "{} {label:24} {command}",
                    if i == selected { "›" } else { " " }
                ),
                HitAction::Palette(i),
                i == selected,
            );
        }
        let col = (self.palette_query.text.width() as u16 + 2).min(inner.width.saturating_sub(1));
        frame.set_cursor_position((inner.x + col, inner.y));
    }
    pub fn demo_refresh(&mut self, _workspace: Workspace) {
        self.status = "Synthetic demo · no network".into();
    }
    pub fn demo_open(&mut self, workspace: Workspace, id: &str) {
        if workspace == Workspace::Chats {
            let fixture = Self::demo(20, 25);
            if let Some(mut chat) = fixture.chat {
                chat.id = id.into();
                self.set_chat(chat);
            }
        } else if let Some(item) = self.items[index(workspace)]
            .iter()
            .find(|i| i.id == id)
            .cloned()
        {
            self.set_item(workspace, item);
        } else if let Some(id) = id.strip_prefix("embed:") {
            self.form = Some(Form::new(
                "Synthetic saved result",
                FormPurpose::Help,
                vec![Field::multiline(
                    "content",
                    "Content",
                    &format!(
                        "# Saved result\n\nSynthetic result {id}. No network request occurred."
                    ),
                )],
            ));
        } else {
            self.status = "Synthetic item unavailable".into();
        }
    }
    /// Explicit synthetic fixture; this never reads credentials, invokes inference or accesses a network.
    pub fn demo(message_count: usize, task_count: usize) -> Self {
        let mut ui = Self::new();
        ui.authenticated = true;
        ui.username = "Native Rust demo".into();
        ui.form = None;
        ui.status = "Synthetic demo · no network · Ratatui + Crossterm".into();
        let text = "# Native Rust presentation demo\n\n**Styled Markdown**, *emphasis*, and a [usable link](https://openmates.org). Unicode: 界 👩‍💻 café.\n\n| Feature | Runtime |\n|---|---|\n| Layout | Rust / Ratatui |\n| Encryption | Rust / AES-GCM |\n\n```rust\nlet private = \"your conversations\";\nprintln!(\"OpenMates\");\n```\n\nNative line A\nNative line B\n\n- Grapheme-aware composer\n- Native pointer hit testing\n\n[Saved result](embed:synthetic-result)";
        let messages=(0..message_count.max(1)).map(|i|Message{id:format!("demo-message-{i}"),role:if i%2==0{"user"}else{"assistant"}.into(),sender:if i%2==0{""}else{"Sophia"}.into(),content:if i==message_count.saturating_sub(1)||i==0{text.into()}else{format!("Message {i}: cached conversations render entirely in Rust. **Private by design.**")},embeds:if i==0{vec![Item{id:"synthetic-result".into(),title:"Native preview".into(),description:"An explicitly synthetic result card".into(),category:"web".into(),fields:json!({"app":"web","skill":"search"}),..Default::default()}]}else{vec![]},..Default::default()}).collect();
        ui.set_chat(Chat {
            id: "demo-chat".into(),
            title: "Native Rust presentation demo".into(),
            category: "general_knowledge".into(),
            messages,
        });
        ui.set_items(
            Workspace::Chats,
            (0..8)
                .map(|i| Item {
                    id: format!("demo-chat-{i}"),
                    title: format!("Private conversation {}", i + 1),
                    description: "Synthetic cached chat".into(),
                    category: "general_knowledge".into(),
                    ..Default::default()
                })
                .collect(),
        );
        ui.set_items(Workspace::Tasks,(0..task_count).map(|i|Item{id:format!("demo-task-{i}"),title:format!("Native Task {}",i+1),description:"A synthetic Task for native layout verification".into(),status:["backlog","todo","in_progress","blocked","done"][i%5].into(),fields:json!({"priority":(["low","medium","high"][i%3]),"project_id":"demo-project"}),..Default::default()}).collect());
        ui.set_items(Workspace::Projects,vec![Item{id:"demo-project".into(),title:"Native workspace".into(),description:"Project Overview, Files and Tasks are native Rust tabs.".into(),fields:json!({"readme":"# Project README\n\nYour encrypted workspace.","files":[{"name":"README.md","path":"README.md","kind":"stored","embedId":"synthetic-readme"}]}),..Default::default()}]);
        ui.set_items(Workspace::Workflows,vec![Item{id:"demo-workflow".into(),title:"Morning briefing".into(),description:"A synthetic workflow graph".into(),category:"productivity".into(),fields:json!({"enabled":false,"nodes":[{"id":"start","type":"trigger","title":"Every morning"},{"id":"report","type":"create_chat_report","title":"Create briefing","config":{"prompt":"Summarize my day"}},{"id":"notify","type":"send_notification","title":"Notify me","config":{"title":"Your briefing is ready"}}],"edges":[{"source":"start","target":"report"},{"source":"report","target":"notify"}],"runs":[{"id":"demo-run","status":"completed","node_runs":[{"node_id":"report","status":"completed"}]}]}),..Default::default()}]);
        ui.set_items(Workspace::Apps,vec![Item{id:"web".into(),title:"Web".into(),description:"Search and read the web".into(),category:"web".into(),fields:json!({"skills":[{"id":"search","name":"Search","description":"Find information on the web"}]}),..Default::default()},Item{id:"calendar".into(),title:"Calendar".into(),description:"Plan your time".into(),category:"calendar".into(),..Default::default()}]);
        ui
    }
}
fn task_group(status: &str) -> &str {
    match status {
        "pending" | "to_do" | "open" | "todo" => "todo",
        "active" | "in_progress" => "in_progress",
        "blocked" => "blocked",
        "completed" | "done" | "cancelled" => "done",
        _ => "backlog",
    }
}
fn task_color(status: &str) -> Color {
    match task_group(status) {
        "todo" => Color::Rgb(50, 173, 230),
        "in_progress" => Color::Rgb(240, 160, 80),
        "blocked" => Color::Rgb(255, 107, 107),
        "done" => Color::Rgb(48, 209, 88),
        _ => Color::Rgb(191, 90, 242),
    }
}
fn task_next(status: &str) -> &'static str {
    match task_group(status) {
        "backlog" => "todo",
        "todo" => "in_progress",
        "in_progress" => "done",
        "blocked" => "in_progress",
        _ => "backlog",
    }
}
fn app_color(category: &str) -> Color {
    match category {
        "web" | "general_knowledge" => BLUE,
        "calendar" | "productivity" => Color::Rgb(139, 92, 246),
        "travel" => Color::Rgb(14, 165, 233),
        "shopping" => Color::Rgb(236, 72, 153),
        "code" => Color::Rgb(34, 197, 94),
        "audio" | "music" => Color::Rgb(245, 158, 11),
        _ => BLUE,
    }
}
fn embed_content(item: &Item) -> String {
    let mut out = format!("# {}\n\n{}", item.title, item.description);
    if let Some(content) = item.fields.get("content") {
        if let Some(text) = content.as_str() {
            out.push_str("\n\n");
            out.push_str(text);
        } else {
            out.push_str("\n\n");
            out.push_str(&display_value(content));
        }
    }
    if let Some(fields) = item.fields.as_object() {
        for (key, value) in fields {
            if sensitive_key(key) || key == "content" {
                continue;
            }
            if value.is_string() || value.is_number() || value.is_boolean() {
                out.push_str(&format!(
                    "\n\n**{}:** {}",
                    key.replace('_', " "),
                    display_value(value)
                ));
            } else if let Some(rows) = value.as_array() {
                for row in rows.iter().take(200) {
                    if let Some(name) = row
                        .get("title")
                        .or_else(|| row.get("name"))
                        .and_then(Value::as_str)
                    {
                        out.push_str(&format!("\n- {name}"));
                    }
                }
            }
        }
    }
    out
}
fn embed_rows(embeds: &[Item], width: usize) -> Vec<Row> {
    let visible = embeds.len().min((width / 28).max(1));
    let card_width = (width / visible.max(1)).max(4);
    let mut output = vec![vec![], vec![], vec![], vec![]];
    for embed in embeds.iter().take(visible) {
        let color = app_color(&embed.category);
        let title = markdown::clean(&embed.title);
        let desc = markdown::clean(&embed.description);
        let app = text_field(&embed.fields, "app");
        let skill = text_field(&embed.fields, "skill");
        let labels = [
            format!("╭─ {title}"),
            desc,
            format!(
                "{} · {}",
                if app.is_empty() { &embed.category } else { app },
                skill
            ),
            format!("╰─ /embed {}", embed.id),
        ];
        for (i, label) in labels.iter().enumerate() {
            let mut text = String::new();
            let mut used = 0;
            for g in unicode_segmentation::UnicodeSegmentation::graphemes(label.as_str(), true) {
                if used + g.width() > card_width.saturating_sub(1) {
                    break;
                }
                text.push_str(g);
                used += g.width();
            }
            text.push_str(&" ".repeat(card_width.saturating_sub(text.width())));
            output[i].push(markdown::Part {
                text,
                style: Style::default()
                    .fg(if i == 1 { TEXT } else { color })
                    .add_modifier(if i == 0 {
                        Modifier::BOLD
                    } else {
                        Modifier::empty()
                    }),
                link: Some(Link::Embed(embed.id.clone())),
            });
        }
    }
    if embeds.len() > visible {
        output.push(markdown::styled(
            format!(
                "{} more saved results · /embed <id>",
                embeds.len() - visible
            ),
            Style::default().fg(MUTED),
        ));
    }
    output
}
fn display_value(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => markdown::clean(text),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::Array(values) => values
            .iter()
            .map(display_value)
            .collect::<Vec<_>>()
            .join(", "),
        Value::Object(values) => values
            .iter()
            .filter(|(key, _)| !sensitive_key(key))
            .map(|(key, value)| format!("{}: {}", key.replace('_', " "), display_value(value)))
            .collect::<Vec<_>>()
            .join(" · "),
    }
}
fn sensitive_key(key: &str) -> bool {
    let key = key.to_lowercase();
    [
        "password",
        "secret",
        "private_key",
        "token",
        "passphrase",
        "key_material",
        "encrypted_",
    ]
    .iter()
    .any(|part| key.contains(part))
}
fn browser_only(route: &str) -> bool {
    [
        "account/email",
        "account/security",
        "account/delete",
        "account/export",
        "account/import",
        "billing/buy-credits",
        "billing/auto-topup/monthly",
        "privacy/hide-personal-data",
        "developers/devices",
        "developers/webhooks",
        "interface/appearance",
        "support/help",
    ]
    .iter()
    .any(|prefix| route == *prefix || route.starts_with(&format!("{prefix}/")))
}
trait MessageLabel {
    fn sender_or_role(&self) -> &str;
}
impl MessageLabel for Message {
    fn sender_or_role(&self) -> &str {
        if self.sender.is_empty() {
            &self.role
        } else {
            &self.sender
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::{Terminal, backend::TestBackend};
    fn ordered_task(id: &str, title: &str, position: Value) -> Item {
        Item {
            id: id.into(),
            title: title.into(),
            status: "todo".into(),
            fields: json!({"position":position}),
            ..Default::default()
        }
    }
    #[test]
    fn task_refresh_orders_presentation_and_preserves_selection_by_task_identity() {
        let mut ui = Ui::new();
        ui.task_order = Ok(openmates_sdk::task_order::TaskOrder::try_new("en-US").unwrap());
        ui.workspace = Workspace::Tasks;
        ui.focus = Focus::Content;
        let a = ordered_task("a", "Later Task", json!(200));
        let z = ordered_task("z", "Earlier Task", json!(100));
        ui.set_items(Workspace::Tasks, vec![a.clone(), z.clone()]);
        assert_eq!(ui.items[index(Workspace::Tasks)][0].id, "z");
        for (width, height) in [(120, 36), (60, 24)] {
            let screen = render(&mut ui, width, height);
            assert!(screen.contains("Earlier Task"));
            assert!(screen.find("Earlier Task").unwrap() < screen.find("Later Task").unwrap());
        }
        ui.key(key(KeyCode::Down));
        assert_eq!(ui.selected[index(Workspace::Tasks)], 1);
        let early = ordered_task("new", "New Task", json!(-0.5));
        ui.set_items(Workspace::Tasks, vec![a.clone(), z.clone(), early.clone()]);
        assert_eq!(
            ui.items[index(Workspace::Tasks)][ui.selected[index(Workspace::Tasks)]].id,
            "a"
        );
        ui.set_items(Workspace::Tasks, vec![early.clone(), z.clone()]);
        assert_eq!(ui.selected[index(Workspace::Tasks)], 1);
        assert_eq!(ui.items[index(Workspace::Tasks)][1].id, "z");
        ui.set_items(
            Workspace::Tasks,
            vec![ordered_task("bad", "Invalid", json!("0"))],
        );
        assert_eq!(ui.items[index(Workspace::Tasks)][1].id, "z");
        assert!(ui.status.contains("position"));
        ui.set_items(Workspace::Projects, vec![a, z, early]);
        assert_eq!(ui.items[index(Workspace::Projects)][0].id, "a");
    }
    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }
    fn ctrl(c: char) -> KeyEvent {
        KeyEvent::new(KeyCode::Char(c), KeyModifiers::CONTROL)
    }
    fn render(ui: &mut Ui, width: u16, height: u16) -> String {
        let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
        terminal.draw(|frame| ui.draw(frame)).unwrap();
        terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect()
    }
    fn left(x: u16, y: u16) -> MouseEvent {
        MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: x,
            row: y,
            modifiers: KeyModifiers::NONE,
        }
    }
    #[test]
    fn all_workspaces_resize_without_invalid_hits() {
        let mut ui = Ui::demo(3, 30);
        for (width, height) in [(1, 1), (12, 5), (24, 9), (45, 18), (96, 30), (160, 45)] {
            for workspace in Workspace::ALL {
                ui.nav(workspace);
                render(&mut ui, width, height);
                assert!(ui.hits.iter().all(|hit| hit.rect.x < width
                    && hit.rect.y < height
                    && hit.rect.right() <= width
                    && hit.rect.bottom() <= height));
                if workspace == Workspace::Settings {
                    ui.settings_toggle();
                }
            }
        }
    }
    #[test]
    fn composer_edits_unicode_in_middle_and_sends_only_on_submit() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.paste("A界B");
        ui.key(key(KeyCode::Left));
        ui.key(key(KeyCode::Backspace));
        ui.paste("é");
        assert_eq!(ui.draft.text.as_str(), "AéB");
        ui.key(KeyEvent::new(KeyCode::Enter, KeyModifiers::ALT));
        ui.paste("second");
        let commands = ui.key(key(KeyCode::Enter));
        assert!(matches!(&commands[..],[UiCommand::Send{chat_id:None,text}]if text=="Aé\nsecondB"));
        assert!(ui.draft.text.is_empty());
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn settings_global_palette_and_pointer_paths_restore_composer_after_navigation() {
        for entry in 0..4 {
            let mut ui = Ui::demo(2, 3);
            ui.paste("private 界 draft");
            let chat = ui.selected_chat_id().map(str::to_owned);
            assert!(ui.key(ctrl('g')).is_empty());
            assert!(ui.focus == Focus::Navigation);
            let commands = match entry {
                0 => ui.key(ctrl('s')),
                1 => ui.key(ctrl('6')),
                2 => {
                    assert!(ui.key(ctrl('p')).is_empty());
                    assert!(ui.paste("/settings").is_empty());
                    ui.key(key(KeyCode::Enter))
                }
                _ => {
                    render(&mut ui, 120, 38);
                    let rect = ui.hits.iter().find(|hit| matches!(hit.action, HitAction::Settings)).unwrap().rect;
                    ui.mouse(left(rect.x, rect.y))
                }
            };
            assert!(matches!(&commands[..], [UiCommand::Refresh(Workspace::Settings)]));
            assert!(ui.settings.as_ref().unwrap().focus_before == Focus::Composer);
            assert!(ui.focus == Focus::Content);
            assert!(ui.form.is_none());
            assert!(matches!(&ui.key(key(KeyCode::Esc))[..], [UiCommand::Refresh(Workspace::Settings)]));
            assert!(ui.settings.is_none());
            assert!(ui.focus == Focus::Composer);
            assert!(ui.key(key(KeyCode::Char('!'))).is_empty());
            assert_eq!(ui.draft.text.as_str(), "private 界 draft!");
            assert_eq!(ui.selected_chat_id().map(str::to_owned), chat);
            assert!(!render(&mut ui, 120, 38).contains("Navigate:"));
        }
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn settings_origin_normalization_preserves_sidebar_focus_and_cancel_ownership() {
        let mut ui = Ui::demo(2, 3);
        ui.sidebar = true;
        ui.focus = Focus::Sidebar;
        ui.paste("ignored outside composer");
        ui.key(ctrl('g'));
        assert!(matches!(&ui.key(ctrl('6'))[..], [UiCommand::Refresh(Workspace::Settings)]));
        assert!(ui.settings.as_ref().unwrap().focus_before == Focus::Sidebar);
        ui.key(ctrl('g'));
        ui.streaming = true;
        assert!(matches!(&ui.key(ctrl('c'))[..], [UiCommand::Cancel]));
        // Closing through the same global shortcut restores the saved owner,
        // even when Navigation was entered from inside Settings.
        assert!(matches!(&ui.key(ctrl('s'))[..], [UiCommand::Refresh(Workspace::Settings)]));
        assert!(ui.settings.is_none());
        assert!(ui.focus == Focus::Sidebar);
        assert!(ui.sidebar);
        assert!(ui.key(key(KeyCode::Down)).is_empty());
        assert_eq!(ui.selected[0], 1);
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn navigation_shortcut_wraps_without_opening_sending_or_changing_the_origin() {
        let mut ui = Ui::demo(20, 3);
        ui.paste("unsent 界 navigation draft");
        let chat = ui.selected_chat_id().map(str::to_owned);
        ui.scroll = 17;
        ui.follow_tail = false;
        assert!(ui.key(ctrl('g')).is_empty());
        assert!(render(&mut ui, 120, 38).contains("Navigate: Chats"));
        assert!(ui.key(key(KeyCode::Left)).is_empty());
        assert!(render(&mut ui, 120, 38).contains("Navigate: Settings"));
        assert!(ui.key(key(KeyCode::Right)).is_empty());
        assert!(render(&mut ui, 120, 38).contains("Navigate: Chats"));
        assert!(ui.key(key(KeyCode::Char('x'))).is_empty());
        assert!(ui.key(key(KeyCode::PageDown)).is_empty());
        assert_eq!(ui.scroll, 17);
        assert!(!ui.follow_tail);
        assert_eq!(ui.selected_chat_id().map(str::to_owned), chat);
        assert_eq!(ui.draft.text.as_str(), "unsent 界 navigation draft");
        assert!(ui.key(key(KeyCode::Esc)).is_empty());
        assert!(ui.focus == Focus::Composer);
        assert!(ui.key(key(KeyCode::Char('!'))).is_empty());
        assert_eq!(ui.draft.text.as_str(), "unsent 界 navigation draft!");
        assert!(!render(&mut ui, 120, 38).contains("Navigate:"));
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn navigation_activation_uses_workspace_refresh_and_settings_restores_origin() {
        let mut ui = Ui::demo(2, 3);
        ui.paste("remember this chat draft");
        assert!(ui.key(ctrl('g')).is_empty());
        assert!(ui.key(key(KeyCode::Right)).is_empty());
        assert!(matches!(&ui.key(key(KeyCode::Enter))[..], [UiCommand::Refresh(Workspace::Apps)]));
        assert!(ui.workspace == Workspace::Apps);
        assert!(ui.focus == Focus::Content);
        assert!(!render(&mut ui, 120, 38).contains("Navigate:"));
        assert!(ui.key(ctrl('g')).is_empty());
        for _ in 0..4 { assert!(ui.key(key(KeyCode::Right)).is_empty()); }
        assert!(matches!(&ui.key(key(KeyCode::Enter))[..], [UiCommand::Refresh(Workspace::Settings)]));
        assert!(ui.settings.is_some());
        assert!(ui.focus == Focus::Content);
        assert!(ui.key(ctrl('g')).is_empty());
        assert!(render(&mut ui, 120, 38).contains("Navigate: Settings"));
        assert!(matches!(&ui.key(key(KeyCode::Enter))[..], [UiCommand::Refresh(Workspace::Settings)]));
        assert!(ui.settings.is_none());
        assert!(ui.focus == Focus::Content);
        ui.settings_toggle();
        ui.key(ctrl('g'));
        ui.key(key(KeyCode::Right)); // Settings wraps to Chats.
        assert!(matches!(&ui.key(key(KeyCode::Enter))[..], [UiCommand::Refresh(Workspace::Chats)]));
        assert!(ui.settings.is_none());
        assert!(ui.workspace == Workspace::Chats);
        // Returning to the original chat must recover its unsent draft.
        let original = Ui::demo(2, 3).chat.unwrap();
        ui.set_chat(original);
        assert_eq!(ui.draft.text.as_str(), "remember this chat draft");
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn navigation_keeps_modal_cancel_and_reverse_tab_owners() {
        let mut ui = Ui::demo(2, 3);
        ui.key(key(KeyCode::F(1)));
        assert!(ui.key(ctrl('g')).is_empty());
        assert!(matches!(ui.form.as_ref().map(|form| &form.purpose), Some(FormPurpose::Help)));
        assert!(ui.focus == Focus::Composer);
        ui.key(key(KeyCode::Esc));
        ui.sidebar = true;
        ui.focus = Focus::Sidebar;
        ui.key(ctrl('g'));
        ui.key(KeyEvent::new(KeyCode::BackTab, KeyModifiers::SHIFT));
        assert!(ui.focus == Focus::Sidebar);
        ui.key(ctrl('g'));
        ui.streaming = true;
        assert!(matches!(&ui.key(ctrl('c'))[..], [UiCommand::Cancel]));
        assert!(ui.focus == Focus::Navigation);
        ui.key(key(KeyCode::Esc));
        assert!(ui.focus == Focus::Sidebar);
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn tab_and_backtab_are_inverse_across_existing_focus_zones_without_changing_draft_or_chat() {
        for sidebar in [false, true] {
            let mut ui = Ui::demo(2, 3);
            ui.sidebar = sidebar;
            ui.paste("unsent 界 navigation draft");
            let chat = ui.selected_chat_id().map(str::to_owned);
            let zones = if sidebar {vec![Focus::Composer, Focus::Sidebar, Focus::Content]} else {vec![Focus::Composer, Focus::Content]};
            ui.scroll = 17;
            ui.follow_tail = false;
            for (i, focus) in zones.iter().enumerate() {
                ui.focus = *focus;
                assert!(ui.key(key(KeyCode::Tab)).is_empty());
                assert!(ui.focus == zones[(i + 1) % zones.len()]);
                for reverse in [KeyEvent::new(KeyCode::BackTab, KeyModifiers::SHIFT), KeyEvent::new(KeyCode::Tab, KeyModifiers::SHIFT)] {
                    ui.focus = *focus;
                    assert!(ui.key(reverse).is_empty());
                    assert!(ui.focus == zones[(i + zones.len() - 1) % zones.len()]);
                }
                assert_eq!(ui.draft.text.as_str(), "unsent 界 navigation draft");
                assert_eq!(ui.selected_chat_id().map(str::to_owned), chat);
                assert_eq!(ui.scroll, 17);
                assert!(!ui.follow_tail);
            }
        }
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn recent_sidebar_edges_and_pages_select_without_scrolling_or_opening_the_chat() {
        let mut ui = Ui::demo(2, 3);
        ui.resize(120, 12);
        ui.paste("keep this local draft");
        let chat = ui.selected_chat_id().map(str::to_owned);
        ui.sidebar = true;
        ui.focus = Focus::Sidebar;
        ui.scroll = 17;
        ui.follow_tail = false;
        let i = index(Workspace::Chats);
        for (code, expected) in [(KeyCode::PageDown, 3), (KeyCode::PageDown, 6), (KeyCode::PageDown, 7), (KeyCode::PageUp, 4), (KeyCode::Home, 0), (KeyCode::End, 7)] {
            assert!(ui.key(key(code)).is_empty());
            assert_eq!(ui.selected[i], expected);
            assert_eq!(ui.scroll, 17);
            assert!(!ui.follow_tail);
            assert_eq!(ui.selected_chat_id().map(str::to_owned), chat);
            assert_eq!(ui.draft.text.as_str(), "keep this local draft");
            assert!(ui.focus == Focus::Sidebar);
        }
        ui.resize(120, 5);
        assert!(ui.key(key(KeyCode::Home)).is_empty());
        assert!(ui.key(key(KeyCode::PageDown)).is_empty());
        assert_eq!(ui.selected[i], 1);
        assert_eq!(ui.scroll, 17);
        ui.set_items(Workspace::Chats, vec![]);
        for code in [KeyCode::End, KeyCode::PageDown, KeyCode::PageUp, KeyCode::Home] {
            assert!(ui.key(key(code)).is_empty());
            assert_eq!(ui.selected[i], 0);
            assert_eq!(ui.scroll, 17);
        }
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn composer_home_end_and_modal_backtab_keep_their_original_owners() {
        let mut ui = Ui::demo(2, 3);
        ui.sidebar = true;
        ui.paste("draft 界");
        assert!(ui.key(key(KeyCode::Home)).is_empty());
        assert_eq!(ui.draft.cursor, 0);
        assert!(ui.key(key(KeyCode::End)).is_empty());
        assert_eq!(ui.draft.cursor, ui.draft.text.len());
        assert!(ui.key(key(KeyCode::F(1))).is_empty());
        assert!(ui.key(KeyEvent::new(KeyCode::BackTab, KeyModifiers::SHIFT)).is_empty());
        assert!(matches!(ui.form.as_ref().map(|form| &form.purpose), Some(FormPurpose::Help)));
        assert!(ui.focus == Focus::Composer);
        assert_eq!(ui.draft.text.as_str(), "draft 界");
        assert!(ui.key(key(KeyCode::Esc)).is_empty());
        ui.focus = Focus::Sidebar;
        ui.streaming = true;
        assert!(matches!(&ui.key(ctrl('c'))[..], [UiCommand::Cancel]));
    }
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
    #[test]
    fn ctrl_p_actions_palette_matches_existing_ctrl_k_and_preserves_draft_navigation() {
        for shortcut in ['p', 'k'] {
            let mut ui = Ui::demo(2, 3);
            ui.paste("unsent 界 draft");
            let original_chat = ui.selected_chat_id().map(str::to_owned);
            ui.palette_query = Editor::from("old filter");
            assert!(ui.key(ctrl(shortcut)).is_empty());
            assert!(matches!(ui.form.as_ref().map(|form| &form.purpose), Some(FormPurpose::Palette)));
            assert!(ui.palette_query.text.is_empty());
            assert!(render(&mut ui, 120, 38).contains("Actions · Escape closes"));
            ui.paste("help");
            assert_eq!(ui.palette_actions(), vec![("Help", "/help")]);
            assert!(ui.key(key(KeyCode::Enter)).is_empty());
            assert!(matches!(ui.form.as_ref().map(|form| &form.purpose), Some(FormPurpose::Help)));
            assert!(render(&mut ui, 120, 38).contains("Keyboard shortcuts"));
            assert!(ui.key(key(KeyCode::Esc)).is_empty());
            assert!(ui.form.is_none());
            assert_eq!(ui.draft.text.as_str(), "unsent 界 draft");
            assert_eq!(ui.selected_chat_id().map(str::to_owned), original_chat);
            assert!(matches!(ui.focus, Focus::Composer));
        }
    }
    #[test]
    fn masked_login_unlock_pair_forms_never_paint_secrets() {
        let mut ui = Ui::new();
        ui.set_authenticated(false);
        ui.paste("private@example.test");
        ui.key(key(KeyCode::Tab));
        ui.paste("sensitive-password-123");
        let screen = render(&mut ui, 100, 32);
        assert!(!screen.contains("sensitive-password-123"));
        assert!(screen.contains('•'));
        ui.set_unlock_required(true);
        ui.paste("secret-vault-passphrase");
        assert!(!render(&mut ui, 70, 25).contains("secret-vault-passphrase"));
        ui.set_pair_pin_required();
        ui.paste("123456");
        assert!(!render(&mut ui, 70, 25).contains("123456"));
    }
    #[test]
    fn pointer_filters_and_selection_release_never_activate() {
        let mut ui = Ui::demo(2, 3);
        render(&mut ui, 120, 32);
        let target = ui
            .hits
            .iter()
            .find(|h| matches!(h.action, HitAction::Nav(Workspace::Tasks)))
            .unwrap()
            .rect;
        let mut event = left(target.x, target.y);
        event.kind = MouseEventKind::Down(MouseButton::Right);
        assert!(ui.mouse(event).is_empty());
        event.kind = MouseEventKind::Up(MouseButton::Left);
        assert!(ui.mouse(event).is_empty());
        event.kind = MouseEventKind::Down(MouseButton::Left);
        event.modifiers = KeyModifiers::SHIFT;
        assert!(ui.mouse(event).is_empty());
        assert_eq!(ui.workspace, Workspace::Chats);
        let commands = ui.key(ctrl('y'));
        assert!(matches!(&commands[..], [UiCommand::SelectionMode(true)]));
        event.modifiers = KeyModifiers::NONE;
        assert!(ui.mouse(event).is_empty());
        ui.key(ctrl('y'));
        render(&mut ui, 120, 32);
        assert!(matches!(
            &ui.mouse(event)[..],
            [UiCommand::Refresh(Workspace::Tasks)]
        ));
    }
    #[test]
    fn resizing_invalidates_click_map_until_repaint() {
        let mut ui = Ui::demo(2, 3);
        render(&mut ui, 100, 32);
        assert!(!ui.hits.is_empty());
        ui.resize(45, 15);
        assert!(ui.hits.is_empty());
        assert!(ui.mouse(left(42, 0)).is_empty());
        render(&mut ui, 45, 15);
        assert!(
            ui.hits
                .iter()
                .all(|h| h.rect.right() <= 45 && h.rect.bottom() <= 15)
        );
    }
    #[test]
    fn modal_and_narrow_settings_block_obscured_navigation_and_preserve_draft() {
        let mut ui = Ui::demo(2, 3);
        ui.paste("draft stays");
        ui.sidebar = true;
        ui.settings_toggle();
        assert!(!ui.sidebar);
        assert!(ui.focus == Focus::Content);
        render(&mut ui, 90, 30);
        assert!(
            !ui.hits
                .iter()
                .any(|h| matches!(h.action, HitAction::Nav(_) | HitAction::Composer))
        );
        ui.settings.as_mut().unwrap().route = "account/security".into();
        ui.resize(160, 40);
        render(&mut ui, 160, 40);
        assert_eq!(ui.settings.as_ref().unwrap().route, "account/security");
        ui.settings_toggle();
        assert!(ui.sidebar);
        assert_eq!(ui.draft.text.as_str(), "draft stays");
        ui.login_form();
        render(&mut ui, 160, 40);
        assert!(ui.hits.iter().all(|h| matches!(
            h.action,
            HitAction::FormField(_)
                | HitAction::FormSubmit
                | HitAction::FormCancel
                | HitAction::Pair
        )));
    }
    #[test]
    fn task_submission_is_typed_and_cannot_duplicate_while_busy() {
        let mut ui = Ui::demo(2, 3);
        ui.nav(Workspace::Tasks);
        ui.edit_form(true);
        let form = ui.form.as_mut().unwrap();
        form.fields[0].editor = Editor::from("Test Task");
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Mutate(Mutation::Create{workspace:Workspace::Tasks,fields})]if fields["title"]=="Test Task"&&fields["priority"]==2&&fields["status"]=="todo")
        );
        assert!(ui.submit_form().is_empty());
        ui.set_error("Offline · retry");
        assert_eq!(
            ui.form.as_ref().unwrap().fields[0].editor.text.as_str(),
            "Test Task"
        );
        assert_eq!(ui.form.as_ref().unwrap().error, "Offline · retry");
        assert!(!ui.submit_form().is_empty());
    }
    #[test]
    fn share_requires_generation_and_result_is_hidden_until_revealed() {
        let mut ui = Ui::demo(2, 3);
        assert!(ui.activate(HitAction::Share).is_empty());
        assert!(matches!(
            ui.form.as_ref().unwrap().purpose,
            FormPurpose::Share(_)
        ));
        assert!(render(&mut ui, 100, 32).contains("Generate Link"));
        let commands = ui.submit_form();
        assert!(matches!(
            &commands[..],
            [UiCommand::Share {
                expires_in: 86400,
                include_sensitive: false,
                ..
            }]
        ));
        let url = "https://openmates.org/share/demo#private-secret";
        ui.set_share_url(url);
        assert!(!render(&mut ui, 100, 35).contains("private-secret"));
        ui.key(key(KeyCode::Char('u')));
        assert!(render(&mut ui, 100, 35).contains("private-secret"));
    }
    #[test]
    fn project_and_workflow_forms_emit_canonical_fields() {
        let mut ui = Ui::demo(2, 3);
        ui.nav(Workspace::Projects);
        ui.edit_form(true);
        let form = ui.form.as_mut().unwrap();
        for field in &mut form.fields {
            match field.key.as_str() {
                "title" => field.editor = Editor::from("Project"),
                "default_focus_id" => {
                    field.editor = Editor::from("f47ac10b-58cc-4372-a567-0e02b2c3d479")
                }
                _ => {}
            }
        }
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Mutate(Mutation::Create{workspace:Workspace::Projects,fields})]if fields["write_mode"]=="always_ask"&&fields["default_focus_id"].is_string())
        );
        ui.form = None;
        ui.nav(Workspace::Workflows);
        ui.edit_form(true);
        let form = ui.form.as_mut().unwrap();
        form.fields[0].editor = Editor::from("Workflow");
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Mutate(Mutation::Create{workspace:Workspace::Workflows,fields})]if fields["graph"]["nodes"].is_array()&&fields["graph"]["edges"].is_array())
        );
    }
    #[test]
    fn background_stream_is_bound_to_matching_chat_on_completion() {
        let mut ui = Ui::demo(1, 1);
        ui.stream(StreamUpdate::Started {
            chat_id: "current".into(),
            message_id: "reply".into(),
            expects_reply: true,
        });
        ui.stream(StreamUpdate::Content {
            content: "incremental".into(),
            thinking: String::new(),
            mate: "Sophia".into(),
        });
        ui.stream(StreamUpdate::Completed {
            chat_id: "other".into(),
            message_id: "reply".into(),
            content: "wrong chat".into(),
        });
        assert_eq!(ui.chat.as_ref().unwrap().messages[0].content, "incremental");
    }
    #[test]
    fn logout_wipes_private_presentation_and_pending_forms() {
        let mut ui = Ui::demo(5, 6);
        ui.paste("private draft");
        ui.share_form();
        ui.clear_private();
        assert!(
            ui.chat.is_none()
                && ui.detail.is_none()
                && ui.items.iter().all(Vec::is_empty)
                && ui.form.is_none()
                && ui.draft.text.is_empty()
                && ui.username.is_empty()
        );
    }
    #[test]
    fn consent_never_autoapproves_and_escape_explicitly_denies() {
        let mut ui = Ui::demo(2, 3);
        let item = Item {
            id: "user_personal_data-email".into(),
            title: "Personal email".into(),
            description: "1 entry requested".into(),
            fields: json!({"entries":[{"email":"owner@example.test"}]}),
            ..Default::default()
        };
        ui.stream(StreamUpdate::Consent {
            request_id: "request-1".into(),
            items: vec![item.clone()],
        });
        assert_eq!(
            ui.form.as_ref().unwrap().fields[0].editor.text.as_str(),
            "false"
        );
        let screen = render(&mut ui, 100, 35);
        assert!(screen.contains("owner@example.test"));
        let commands = ui.key(key(KeyCode::Esc));
        assert!(
            matches!(&commands[..],[UiCommand::Consent{request_id,approved_ids}]if request_id=="request-1"&&approved_ids.is_empty())
        );
        ui.stream(StreamUpdate::Consent {
            request_id: "request-2".into(),
            items: vec![item],
        });
        ui.key(key(KeyCode::Char(' ')));
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Consent{request_id,approved_ids}]if request_id=="request-2"&&approved_ids==&["user_personal_data-email"])
        );
    }
    #[test]
    fn graph_editor_preserves_edges_and_types_config() {
        let mut ui = Ui::demo(2, 3);
        ui.demo_open(Workspace::Workflows, "demo-workflow");
        ui.activate(HitAction::Link(Link::Node(1)));
        let form = ui.form.as_mut().unwrap();
        let prompt = form
            .fields
            .iter_mut()
            .find(|f| f.key == "config.prompt")
            .unwrap();
        prompt.editor = Editor::from("Updated briefing");
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Mutate(Mutation::Update{fields,..})]if fields["graph"]["nodes"][1]["config"]["prompt"]=="Updated briefing"&&fields["graph"]["edges"].as_array().unwrap().len()==2)
        );
    }
    #[test]
    fn project_file_download_preserves_authority_scope_and_explicit_destination() {
        let mut ui = Ui::demo(2, 3);
        let commands = ui.activate(HitAction::Link(Link::ProjectFile {
            project: "project-id".into(),
            embed: "embed-id".into(),
            name: "README.md".into(),
        }));
        assert!(commands.is_empty());
        assert!(ui.submit_form().is_empty());
        ui.form.as_mut().unwrap().fields[0].editor =
            Editor::from("/tmp/openmates-ui-unit-test-export.md");
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Download{workspace:Workspace::Projects,id,destination,overwrite:false}]if id=="project-id/embed-id"&&destination==&std::path::PathBuf::from("/tmp/openmates-ui-unit-test-export.md"))
        );
    }
    #[test]
    fn opening_embed_preserves_chat_origin_and_composer_draft() {
        let mut ui = Ui::demo(2, 3);
        ui.paste("Preserved draft");
        let chat_id = ui.chat.as_ref().unwrap().id.clone();
        ui.set_item(
            Workspace::Apps,
            Item {
                id: "embed:result".into(),
                title: "Result".into(),
                description: "Saved result".into(),
                ..Default::default()
            },
        );
        assert!(ui.chat.is_none());
        ui.back();
        assert_eq!(ui.chat.as_ref().unwrap().id, chat_id);
        assert_eq!(ui.draft.text.as_str(), "Preserved draft");
    }
    #[test]
    fn drafts_are_isolated_by_chat_and_survive_workspace_navigation() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        let chat = |id: &str| Chat {
            id: id.into(),
            title: id.into(),
            ..Default::default()
        };
        ui.set_chat(chat("a"));
        ui.paste("draft A");
        ui.set_chat(chat("b"));
        assert!(ui.draft.text.is_empty());
        ui.paste("draft B");
        ui.nav(Workspace::Tasks);
        assert!(ui.draft.text.is_empty());
        ui.set_chat(chat("a"));
        assert_eq!(ui.draft.text.as_str(), "draft A");
        ui.set_chat(chat("b"));
        assert_eq!(ui.draft.text.as_str(), "draft B");
        ui.clear_private();
        assert!(ui.drafts.is_empty());
    }
    #[test]
    fn failed_or_cancelled_send_restores_retry_draft_but_ack_does_not() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.set_chat(Chat {
            id: "a".into(),
            ..Default::default()
        });
        ui.paste("retry me");
        ui.send();
        assert!(ui.draft.text.is_empty());
        ui.set_error("Offline");
        assert_eq!(ui.draft.text.as_str(), "retry me");
        ui.send();
        let commands = ui.key(ctrl('c'));
        assert!(matches!(&commands[..], [UiCommand::Cancel]));
        assert!(ui.draft.text.is_empty());
        assert!(ui.pending_send.is_some());
        ui.set_status("Cancelled");
        assert_eq!(ui.draft.text.as_str(), "retry me");
        ui.send();
        ui.send_succeeded();
        ui.set_chat(Chat {
            id: "a".into(),
            ..Default::default()
        });
        assert!(ui.draft.text.is_empty());
        assert!(ui.pending_send.is_none());
    }
    #[test]
    fn new_chat_assignment_migrates_retry_and_next_draft() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.paste("first message");
        ui.send();
        ui.paste("next message draft");
        ui.stream(StreamUpdate::Started {
            chat_id: "assigned".into(),
            message_id: "response".into(),
            expects_reply: true,
        });
        assert_eq!(ui.draft.text.as_str(), "next message draft");
        ui.set_status("Cancelled");
        assert_eq!(ui.draft.text.as_str(), "next message draft");
        assert_eq!(
            ui.drafts.get("__retry__:assigned").unwrap().as_str(),
            "first message"
        );
        ui.set_chat(Chat {
            id: "other".into(),
            ..Default::default()
        });
        assert!(ui.draft.text.is_empty());
        ui.set_chat(Chat {
            id: "assigned".into(),
            ..Default::default()
        });
        assert_eq!(ui.draft.text.as_str(), "next message draft");
        ui.draft.clear();
        ui.command("/retry");
        assert_eq!(ui.draft.text.as_str(), "first message");
    }
    fn native_skill() -> Item {
        Item {
            id: "skill:web/search".into(),
            title: "Search the web".into(),
            description: "Find results".into(),
            fields: json!({"app_id":"web","skill_id":"search","execution_available":true,"pricing":{"fixed":1},"input_schema":{"type":"object","properties":{"query":{"type":"string","minLength":1},"count":{"type":"integer","default":5,"minimum":1,"maximum":20}},"required":["query"]}}),
            ..Default::default()
        }
    }
    #[test]
    fn app_skill_requires_typed_input_then_explicit_run_confirmation() {
        let mut ui = Ui::demo(2, 3);
        ui.set_item(Workspace::Apps, native_skill());
        ui.activate(HitAction::SkillRun);
        assert!(matches!(
            ui.form.as_ref().unwrap().purpose,
            FormPurpose::AppInput(_)
        ));
        assert!(ui.submit_form().is_empty());
        ui.form
            .as_mut()
            .unwrap()
            .fields
            .iter_mut()
            .find(|f| f.key == "/query")
            .unwrap()
            .editor = Editor::from("native Rust");
        assert!(ui.submit_form().is_empty());
        assert!(matches!(
            ui.form.as_ref().unwrap().purpose,
            FormPurpose::AppConfirm { .. }
        ));
        let screen = render(&mut ui, 100, 35);
        assert!(screen.contains("native Rust") && screen.contains("1 credits per request"));
        assert!(ui.submit_form().is_empty());
        ui.paste("RUN");
        let commands = ui.submit_form();
        assert!(
            matches!(&commands[..],[UiCommand::Mutate(Mutation::Create{workspace:Workspace::Apps,fields})]if fields==&json!({"app":"web","skill":"search","input":{"query":"native Rust","count":5}}))
        );
        assert!(ui.submit_form().is_empty());
        ui.set_error("Provider unavailable");
        assert!(matches!(
            ui.form.as_ref().unwrap().purpose,
            FormPurpose::AppConfirm { .. }
        ));
        ui.key(key(KeyCode::Esc));
        assert!(matches!(
            ui.form.as_ref().unwrap().purpose,
            FormPurpose::AppInput(_)
        ));
        assert_eq!(
            ui.form
                .as_ref()
                .unwrap()
                .fields
                .iter()
                .find(|f| f.key == "/query")
                .unwrap()
                .editor
                .text
                .as_str(),
            "native Rust"
        );
    }
    #[test]
    fn app_catalog_skill_targets_and_history_are_native() {
        let mut ui = Ui::demo(2, 3);
        ui.demo_open(Workspace::Apps, "web");
        ui.detail.as_mut().unwrap().fields["skills"] =
            json!([{"id":"search","name":"Search","description":"Search the web"}]);
        ui.detail_tab = 1;
        render(&mut ui, 100, 35);
        let rect=ui.hits.iter().find(|h|matches!(&h.action,HitAction::Link(Link::Skill{app,skill})if app=="web"&&skill=="search")).unwrap().rect;
        let commands = ui.mouse(left(rect.x, rect.y));
        assert!(
            matches!(&commands[..],[UiCommand::Open(Workspace::Apps,id)]if id=="skill:web/search")
        );
        ui.set_item(Workspace::Apps, native_skill());
        ui.set_item(Workspace::Apps,Item{id:"result:run".into(),title:"Search results".into(),fields:json!({"content":{"results":[{"title":"Result title","url":"https://openmates.org"}]}}),..Default::default()});
        assert!(render(&mut ui, 100, 35).contains("Result title"));
        ui.back();
        assert_eq!(ui.detail.as_ref().unwrap().id, "skill:web/search");
        ui.back();
        assert_eq!(ui.detail.as_ref().unwrap().id, "web");
    }
    #[test]
    fn unsupported_skill_schema_cannot_present_fake_run_form() {
        let mut ui = Ui::demo(2, 3);
        let mut skill = native_skill();
        skill.fields["input_schema"] = json!({"type":"object","properties":{"x":{"oneOf":[{"type":"integer"},{"type":"string"}]}}});
        ui.set_item(Workspace::Apps, skill);
        ui.activate(HitAction::SkillRun);
        assert!(ui.form.is_none());
        assert!(ui.status.contains("unavailable"));
    }
    #[test]
    fn live_stream_keeps_user_turn_and_remaps_only_pending_assistant() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.set_chat(Chat {
            id: "live-chat".into(),
            ..Default::default()
        });
        ui.paste("Keep my original message");
        ui.send();
        let started = || StreamUpdate::Started {
            chat_id: "live-chat".into(),
            message_id: "human-id".into(),
            expects_reply: true,
        };
        ui.stream(started());
        ui.stream(started());
        let messages = &ui.chat.as_ref().unwrap().messages;
        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].role, "user");
        assert_eq!(messages[0].id, "human-id");
        assert_eq!(messages[0].content, "Keep my original message");
        ui.stream(StreamUpdate::Content {
            content: "Partial reply".into(),
            thinking: "Reasoning".into(),
            mate: "Sophia".into(),
        });
        ui.stream(started());
        ui.stream(StreamUpdate::Content {
            content: "Final reply".into(),
            thinking: "Reasoning complete".into(),
            mate: "Sophia".into(),
        });
        assert_eq!(ui.chat.as_ref().unwrap().messages.len(), 2);
        ui.stream(StreamUpdate::Completed {
            chat_id: "live-chat".into(),
            message_id: "assistant-id".into(),
            content: "Final restored reply".into(),
        });
        let messages = &ui.chat.as_ref().unwrap().messages;
        assert_eq!(messages.len(), 2);
        assert_eq!(
            (&messages[0].role, &messages[0].id, &messages[0].content),
            (
                &"user".into(),
                &"human-id".into(),
                &"Keep my original message".into()
            )
        );
        assert_eq!(
            (&messages[1].role, &messages[1].id, &messages[1].content),
            (
                &"assistant".into(),
                &"assistant-id".into(),
                &"Final restored reply".into()
            )
        );
        assert_eq!(messages[1].thinking, "Reasoning complete");
        assert_eq!(messages[1].sender, "Sophia");
        assert!(!ui.streaming && ui.pending_send.is_none() && ui.active_turn.is_none());
    }
    #[test]
    fn ordinary_team_completion_preserves_human_text_without_fake_assistant() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.set_chat(Chat {
            id: "team-chat".into(),
            ..Default::default()
        });
        ui.paste("Hello Team");
        ui.send();
        ui.stream(StreamUpdate::Started {
            chat_id: "team-chat".into(),
            message_id: "human-id".into(),
            expects_reply: false,
        });
        ui.stream(StreamUpdate::Completed {
            chat_id: "team-chat".into(),
            message_id: "human-id".into(),
            content: String::new(),
        });
        let messages = &ui.chat.as_ref().unwrap().messages;
        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].role, "user");
        assert_eq!(messages[0].id, "human-id");
        assert_eq!(messages[0].content, "Hello Team");
        assert_eq!(ui.status, "Message delivered");
        assert!(!ui.streaming && ui.pending_send.is_none());
    }
    #[test]
    fn submitted_or_admitted_failure_never_retries_a_potentially_delivered_turn() {
        for admitted in [false, true] {
            let mut ui = Ui::new();
            ui.set_authenticated(true);
            ui.set_chat(Chat {
                id: "delivery-chat".into(),
                ..Default::default()
            });
            ui.paste("Do not duplicate this message");
            ui.send();
            ui.stream(StreamUpdate::Started {
                chat_id: "delivery-chat".into(),
                message_id: "human-id".into(),
                expects_reply: true,
            });
            ui.stream(StreamUpdate::Submitted {
                chat_id: "delivery-chat".into(),
                message_id: "human-id".into(),
            });
            if admitted {
                ui.stream(StreamUpdate::Admitted {
                    chat_id: "delivery-chat".into(),
                    message_id: "human-id".into(),
                });
            }
            ui.set_error("Connection interrupted");
            assert!(ui.draft.text.is_empty());
            assert!(ui.pending_send.is_none());
            assert_eq!(
                ui.uncertain_turns["delivery-chat"].text.as_str(),
                "Do not duplicate this message"
            );
            assert_eq!(ui.uncertain_turns["delivery-chat"].admitted, admitted);
            assert!(ui.command("/retry").is_empty());
            assert!(ui.draft.text.is_empty());
            let commands = ui.command("/copy-pending");
            assert!(
                matches!(&commands[..],[UiCommand::Copy(text)]if text=="Do not duplicate this message")
            );
            let commands = ui.command("/pending");
            assert!(
                matches!(&commands[..],[UiCommand::Open(Workspace::Chats,id)]if id=="delivery-chat")
            );
            ui.paste("Another message");
            assert!(ui.send().is_empty());
            ui.set_chat(Chat {
                id: "delivery-chat".into(),
                messages: vec![Message {
                    id: "human-id".into(),
                    role: "user".into(),
                    content: "Do not duplicate this message".into(),
                    ..Default::default()
                }],
                ..Default::default()
            });
            assert!(ui.uncertain_turns.is_empty());
            assert_eq!(ui.draft.text.as_str(), "Another message");
        }
    }
    #[test]
    fn submitted_before_started_still_preserves_new_chat_delivery_uncertainty() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.paste("First message");
        ui.send();
        ui.stream(StreamUpdate::Submitted {
            chat_id: "assigned-chat".into(),
            message_id: "human-id".into(),
        });
        ui.set_status("Cancelled");
        assert!(ui.draft.text.is_empty());
        assert_eq!(
            ui.uncertain_turns["assigned-chat"].text.as_str(),
            "First message"
        );
        assert!(ui.status.contains("Delivery uncertain"));
        ui.clear_private();
        assert!(ui.uncertain_turns.is_empty());
    }
    #[test]
    fn pre_submission_failure_removes_optimistic_turn_before_retry() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.set_chat(Chat {
            id: "chat".into(),
            ..Default::default()
        });
        ui.paste("Not dispatched");
        ui.send();
        ui.stream(StreamUpdate::Started {
            chat_id: "chat".into(),
            message_id: "human".into(),
            expects_reply: true,
        });
        assert_eq!(ui.chat.as_ref().unwrap().messages.len(), 1);
        ui.set_error("Failed before dispatch");
        assert!(ui.chat.as_ref().unwrap().messages.is_empty());
        assert_eq!(ui.draft.text.as_str(), "Not dispatched");
        assert!(ui.uncertain_turns.is_empty());
    }
    #[test]
    fn cancel_intent_waits_for_queued_delivery_fences_before_deciding_retry() {
        for command in ["keyboard", "slash"] {
            let mut ui = Ui::new();
            ui.set_authenticated(true);
            ui.set_chat(Chat {
                id: "chat".into(),
                ..Default::default()
            });
            ui.paste("Only send once");
            ui.send();
            let commands = if command == "keyboard" {
                ui.key(ctrl('c'))
            } else {
                ui.command("/stop")
            };
            assert!(matches!(&commands[..], [UiCommand::Cancel]));
            assert!(ui.pending_send.is_some());
            assert!(ui.draft.text.is_empty());
            ui.background_stream(StreamUpdate::Started {
                chat_id: "chat".into(),
                message_id: "human".into(),
                expects_reply: true,
            });
            ui.background_stream(StreamUpdate::Submitted {
                chat_id: "chat".into(),
                message_id: "human".into(),
            });
            ui.background_stream(StreamUpdate::Admitted {
                chat_id: "chat".into(),
                message_id: "human".into(),
            });
            ui.set_error("Cancelled");
            assert!(ui.draft.text.is_empty());
            assert!(ui.pending_send.is_none());
            assert!(ui.uncertain_turns["chat"].admitted);
            assert!(ui.command("/retry").is_empty());
            assert!(ui.draft.text.is_empty());
        }
    }
    #[test]
    fn background_delivery_settles_send_without_navigating_or_changing_visible_draft() {
        let mut ui = Ui::demo(2, 3);
        ui.paste("Original chat send");
        ui.send();
        let source = ui.chat.as_ref().unwrap().id.clone();
        ui.nav(Workspace::Tasks);
        ui.focus = Focus::Composer;
        ui.paste("Visible workspace draft");
        let visible = ui.draft.text.to_string();
        let selected = ui.selected[4];
        ui.background_stream(StreamUpdate::Started {
            chat_id: source.clone(),
            message_id: "human".into(),
            expects_reply: true,
        });
        ui.background_stream(StreamUpdate::Submitted {
            chat_id: source.clone(),
            message_id: "human".into(),
        });
        ui.background_stream(StreamUpdate::Admitted {
            chat_id: source.clone(),
            message_id: "human".into(),
        });
        ui.background_stream(StreamUpdate::Content {
            content: "Hidden streamed reply".into(),
            thinking: String::new(),
            mate: "Sophia".into(),
        });
        assert_eq!(ui.workspace, Workspace::Tasks);
        assert!(ui.chat.is_none());
        assert_eq!(ui.draft.text.as_str(), visible);
        ui.background_stream(StreamUpdate::Completed {
            chat_id: source,
            message_id: "assistant".into(),
            content: "Finished reply".into(),
        });
        assert_eq!(ui.workspace, Workspace::Tasks);
        assert!(ui.chat.is_none() && ui.pending_send.is_none() && ui.active_turn.is_none());
        assert_eq!(ui.draft.text.as_str(), visible);
        assert_eq!(ui.selected[4], selected);
        assert!(ui.uncertain_turns.is_empty());
    }
    #[test]
    fn background_new_chat_assignment_migrates_saved_draft_without_changing_view() {
        let mut ui = Ui::new();
        ui.set_authenticated(true);
        ui.paste("First message");
        ui.send();
        ui.paste("Follow-up draft");
        ui.nav(Workspace::Projects);
        let visible = ui.draft.text.to_string();
        ui.background_stream(StreamUpdate::Started {
            chat_id: "assigned".into(),
            message_id: "human".into(),
            expects_reply: false,
        });
        assert_eq!(ui.workspace, Workspace::Projects);
        assert!(ui.chat.is_none());
        assert_eq!(ui.draft.text.as_str(), visible);
        assert_eq!(ui.drafts["assigned"].as_str(), "Follow-up draft");
        ui.background_stream(StreamUpdate::Submitted {
            chat_id: "assigned".into(),
            message_id: "human".into(),
        });
        ui.background_stream(StreamUpdate::Admitted {
            chat_id: "assigned".into(),
            message_id: "human".into(),
        });
        ui.background_stream(StreamUpdate::Completed {
            chat_id: "assigned".into(),
            message_id: "human".into(),
            content: String::new(),
        });
        assert!(ui.pending_send.is_none());
        assert_eq!(ui.workspace, Workspace::Projects);
        assert!(ui.chat.is_none());
    }
    #[test]
    fn background_consent_identifies_origin_without_navigation_or_approval() {
        let mut ui = Ui::demo(2, 3);
        ui.paste("Request");
        ui.send();
        let source = ui.chat.as_ref().unwrap().id.clone();
        ui.items[0].push(Item {
            id: source.clone(),
            title: "Original private chat".into(),
            ..Default::default()
        });
        ui.nav(Workspace::Tasks);
        ui.background_stream(StreamUpdate::Started {
            chat_id: source,
            message_id: "human".into(),
            expects_reply: true,
        });
        ui.background_stream(StreamUpdate::Consent {
            request_id: "consent".into(),
            items: vec![Item {
                id: "memory-category".into(),
                title: "Memory category".into(),
                ..Default::default()
            }],
        });
        assert_eq!(ui.workspace, Workspace::Tasks);
        assert!(ui.chat.is_none());
        assert_eq!(
            ui.form.as_ref().unwrap().fields[0].editor.text.as_str(),
            "false"
        );
        assert!(render(&mut ui, 100, 35).contains("Requested by: Original private chat"));
    }
}

#[cfg(test)]
#[path = "ui_live_tests.rs"]
mod live_tests;

#[cfg(test)]
#[path = "ui_cached_chat_tests.rs"]
mod cached_chat_tests;

#[cfg(test)]
#[path = "ui_focus_parity_tests.rs"]
mod focus_parity_tests;
