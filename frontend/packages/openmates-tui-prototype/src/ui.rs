use crate::model::{Action, Embed, MAX_DRAFT, Message, RichLine, Snapshot, UiState};
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Clear, Paragraph, Wrap},
};
use unicode_width::UnicodeWidthStr;

const NAV: &[&str] = &["chats", "apps", "projects", "workflows", "tasks"];
const BASE: Color = Color::Rgb(17, 22, 31);
const MUTED: Color = Color::Rgb(155, 168, 185);
const ACCENT: Color = Color::Rgb(100, 185, 242);

#[derive(Clone, Debug)]
pub struct Ui {
    pub snapshot: Snapshot,
    pub draft: String,
    pub focus: Focus,
    pub selected_sidebar: usize,
    pub selected_embed: usize,
    pub selected_row: usize,
    pub scroll_up: u16,
    pub hits: Vec<Hit>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Focus {
    Composer,
    Sidebar,
    Embeds,
    Rows,
}

#[derive(Clone, Debug)]
pub struct Hit {
    pub rect: Rect,
    pub action: HitAction,
}

#[derive(Clone, Debug)]
pub enum HitAction {
    Nav(String),
    Chat(String),
    Category(String),
    Embed(String),
    WorkspaceRow(String),
    Sidebar,
    Composer,
    Back,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Intent {
    pub name: &'static str,
    pub id: Option<String>,
    pub value: Option<String>,
    pub open: Option<bool>,
}

impl Intent {
    fn new(name: &'static str) -> Self {
        Self {
            name,
            id: None,
            value: None,
            open: None,
        }
    }
    fn id(name: &'static str, id: String) -> Self {
        Self {
            id: Some(id),
            ..Self::new(name)
        }
    }
    fn value(name: &'static str, value: String) -> Self {
        Self {
            value: Some(value),
            ..Self::new(name)
        }
    }
    fn sidebar(open: bool) -> Self {
        Self {
            open: Some(open),
            ..Self::new("set_sidebar")
        }
    }
    pub fn action<'a>(&'a self, snapshot: &'a Snapshot) -> Action<'a> {
        Action {
            v: 1,
            r#type: "action",
            epoch: snapshot.epoch,
            scope: &snapshot.scope,
            action: self.name,
            id: self.id.as_deref(),
            value: self.value.as_deref(),
            open: self.open,
        }
    }
}

impl Ui {
    pub fn new(snapshot: Snapshot) -> Self {
        let draft = snapshot.state.draft.clone();
        Self {
            snapshot,
            draft,
            focus: Focus::Composer,
            selected_sidebar: 0,
            selected_embed: 0,
            selected_row: 0,
            scroll_up: 0,
            hits: Vec::new(),
        }
    }
    pub fn update(&mut self, incoming: Snapshot) -> bool {
        if incoming.epoch <= self.snapshot.epoch {
            return false;
        }
        let scope_changed = incoming.scope != self.snapshot.scope;
        if scope_changed {
            self.focus = Focus::Composer;
            self.scroll_up = 0;
            self.selected_embed = 0;
        }
        self.draft = incoming.state.draft.clone();
        self.snapshot = incoming;
        true
    }
    fn embeds(&self) -> Vec<&Embed> {
        self.snapshot
            .state
            .messages
            .iter()
            .flat_map(|m| m.embeds.iter())
            .collect()
    }
    fn toggle_sidebar(&mut self) -> Intent {
        self.snapshot.state.sidebar_open = !self.snapshot.state.sidebar_open;
        self.focus = if self.snapshot.state.sidebar_open {
            Focus::Sidebar
        } else {
            Focus::Composer
        };
        Intent::sidebar(self.snapshot.state.sidebar_open)
    }
    pub fn key(&mut self, event: KeyEvent) -> Vec<Intent> {
        let mut out = Vec::new();
        if event.modifiers.contains(KeyModifiers::CONTROL) && event.code == KeyCode::Char('b') {
            out.push(self.toggle_sidebar());
            return out;
        }
        match event.code {
            KeyCode::Esc => {
                if self.focus == Focus::Embeds || self.focus == Focus::Rows {
                    self.focus = Focus::Composer;
                } else if self.snapshot.state.sidebar_open {
                    self.snapshot.state.sidebar_open = false;
                    self.focus = Focus::Composer;
                    out.push(Intent::sidebar(false));
                } else {
                    out.push(Intent::new("back"));
                }
            }
            KeyCode::Tab => {
                self.focus = match self.focus {
                    Focus::Composer if self.snapshot.state.sidebar_open => Focus::Sidebar,
                    Focus::Composer
                        if self.snapshot.state.view != "chats"
                            && !self.snapshot.state.workspace_rows.is_empty() =>
                    {
                        Focus::Rows
                    }
                    Focus::Composer if !self.embeds().is_empty() => Focus::Embeds,
                    Focus::Sidebar if !self.embeds().is_empty() => Focus::Embeds,
                    Focus::Sidebar
                        if self.snapshot.state.view != "chats"
                            && !self.snapshot.state.workspace_rows.is_empty() =>
                    {
                        Focus::Rows
                    }
                    _ => Focus::Composer,
                };
            }
            KeyCode::Up if self.focus == Focus::Sidebar => {
                self.selected_sidebar = self.selected_sidebar.saturating_sub(1)
            }
            KeyCode::Down if self.focus == Focus::Sidebar => {
                self.selected_sidebar = (self.selected_sidebar + 1)
                    .min(self.snapshot.state.chats.len().saturating_sub(1))
            }
            KeyCode::Up if self.focus == Focus::Rows => {
                self.selected_row = self.selected_row.saturating_sub(1)
            }
            KeyCode::Down if self.focus == Focus::Rows => {
                self.selected_row = (self.selected_row + 1)
                    .min(self.snapshot.state.workspace_rows.len().saturating_sub(1))
            }
            KeyCode::Left if self.focus == Focus::Embeds => {
                self.selected_embed = self.selected_embed.saturating_sub(1)
            }
            KeyCode::Right if self.focus == Focus::Embeds => {
                self.selected_embed =
                    (self.selected_embed + 1).min(self.embeds().len().saturating_sub(1))
            }
            KeyCode::Enter if self.focus == Focus::Sidebar => {
                if let Some(chat) = self.snapshot.state.chats.get(self.selected_sidebar) {
                    out.push(Intent::id("open_chat", chat.id.clone()));
                }
            }
            KeyCode::Enter if self.focus == Focus::Embeds => {
                if let Some(embed) = self.embeds().get(self.selected_embed) {
                    out.push(Intent::id("open_embed", embed.id.clone()));
                }
            }
            KeyCode::Enter if self.focus == Focus::Rows => {
                if let Some(row) = self.snapshot.state.workspace_rows.get(self.selected_row) {
                    out.push(Intent::id("open_workspace_item", row.id.clone()));
                }
            }
            KeyCode::Enter
                if self.focus == Focus::Composer && event.modifiers.contains(KeyModifiers::ALT) =>
            {
                if self.draft.len() < MAX_DRAFT {
                    self.draft.push('\n');
                    out.push(Intent::value("draft_changed", self.draft.clone()));
                }
            }
            KeyCode::Enter if self.focus == Focus::Composer => {
                if !self.draft.trim().is_empty() {
                    out.push(Intent::value("send_message", self.draft.clone()));
                    self.draft.clear();
                }
            }
            KeyCode::Backspace if self.focus == Focus::Composer => {
                if self.draft.pop().is_some() {
                    out.push(Intent::value("draft_changed", self.draft.clone()));
                }
            }
            KeyCode::Char(c)
                if self.focus == Focus::Composer
                    && !event
                        .modifiers
                        .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) =>
            {
                if self.draft.len() + c.len_utf8() <= MAX_DRAFT {
                    self.draft.push(c);
                    out.push(Intent::value("draft_changed", self.draft.clone()));
                }
            }
            KeyCode::PageUp => self.scroll_up = self.scroll_up.saturating_add(10),
            KeyCode::PageDown => self.scroll_up = self.scroll_up.saturating_sub(10),
            _ => {}
        }
        out
    }
    pub fn mouse(&mut self, event: MouseEvent) -> Vec<Intent> {
        match event.kind {
            MouseEventKind::ScrollUp => {
                self.scroll_up = self.scroll_up.saturating_add(3);
                return Vec::new();
            }
            MouseEventKind::ScrollDown => {
                self.scroll_up = self.scroll_up.saturating_sub(3);
                return Vec::new();
            }
            MouseEventKind::Down(MouseButton::Left) => {}
            _ => return Vec::new(),
        }
        let hit = self
            .hits
            .iter()
            .rev()
            .find(|hit| {
                event.column >= hit.rect.x
                    && event.column < hit.rect.right()
                    && event.row >= hit.rect.y
                    && event.row < hit.rect.bottom()
            })
            .cloned();
        match hit.map(|hit| hit.action) {
            Some(HitAction::Nav(id)) => vec![Intent::id("open_workspace", id)],
            Some(HitAction::Chat(id)) => vec![Intent::id("open_chat", id)],
            Some(HitAction::Category(id)) => vec![Intent::id("select_category", id)],
            Some(HitAction::Embed(id)) => vec![Intent::id("open_embed", id)],
            Some(HitAction::WorkspaceRow(id)) => vec![Intent::id("open_workspace_item", id)],
            Some(HitAction::Sidebar) => vec![self.toggle_sidebar()],
            Some(HitAction::Composer) => {
                self.focus = Focus::Composer;
                Vec::new()
            }
            Some(HitAction::Back) => vec![Intent::new("back")],
            None => Vec::new(),
        }
    }
    fn hit(&mut self, rect: Rect, action: HitAction) {
        if rect.width > 0 && rect.height > 0 {
            self.hits.push(Hit { rect, action });
        }
    }
}

fn rgb(value: &str, fallback: Color) -> Color {
    let v = value.strip_prefix('#').unwrap_or(value);
    if v.len() != 6 {
        return fallback;
    }
    match u32::from_str_radix(v, 16) {
        Ok(n) => Color::Rgb((n >> 16) as u8, (n >> 8) as u8, n as u8),
        Err(_) => fallback,
    }
}

fn sanitize(value: &str) -> String {
    value
        .chars()
        .map(|c| {
            if c == '\n' || c == '\t' {
                c
            } else if c.is_control() || c == '\u{1b}' {
                ' '
            } else {
                c
            }
        })
        .collect()
}

fn clip(value: &str, width: usize) -> String {
    let mut result = String::new();
    let mut used = 0;
    for c in sanitize(value).chars() {
        let cell = unicode_width::UnicodeWidthChar::width(c).unwrap_or(0);
        if used + cell > width {
            break;
        }
        result.push(c);
        used += cell;
    }
    result
}

fn rich_line(line: &RichLine) -> Line<'static> {
    Line::from(
        line.spans
            .iter()
            .map(|span| {
                let mut style = Style::default().fg(rgb(&span.color, Color::White));
                if span.bold {
                    style = style.add_modifier(Modifier::BOLD);
                }
                Span::styled(sanitize(&span.text), style)
            })
            .collect::<Vec<_>>(),
    )
}

fn markdown_lines(content: &str) -> Vec<Line<'static>> {
    content
        .lines()
        .map(|raw| {
            let raw = sanitize(raw);
            let heading = raw.trim_start().starts_with('#');
            let text = if heading {
                raw.trim_start_matches('#').trim_start().to_owned()
            } else {
                raw
            };
            let mut spans = Vec::new();
            let mut bold = heading;
            let mut rest = text.as_str();
            while let Some(i) = rest.find("**") {
                if i > 0 {
                    spans.push(Span::styled(
                        rest[..i].to_owned(),
                        Style::default()
                            .fg(if heading { ACCENT } else { Color::White })
                            .add_modifier(if bold {
                                Modifier::BOLD
                            } else {
                                Modifier::empty()
                            }),
                    ));
                }
                bold = !bold;
                rest = &rest[i + 2..];
            }
            spans.push(Span::styled(
                rest.to_owned(),
                Style::default()
                    .fg(if heading { ACCENT } else { Color::White })
                    .add_modifier(if bold {
                        Modifier::BOLD
                    } else {
                        Modifier::empty()
                    }),
            ));
            Line::from(spans)
        })
        .collect()
}

fn message_lines(message: &Message) -> Vec<Line<'static>> {
    let role_color = if message.role == "user" {
        Color::Rgb(255, 187, 96)
    } else {
        ACCENT
    };
    let fallback = if message.role == "user" {
        "You"
    } else {
        "OpenMates"
    };
    let name = message
        .sender_name
        .as_deref()
        .filter(|name| !name.trim().is_empty())
        .unwrap_or(fallback);
    let name: String = name
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let mut lines = vec![Line::styled(
        name,
        Style::default().fg(role_color).add_modifier(Modifier::BOLD),
    )];
    if message.lines.is_empty() {
        lines.extend(markdown_lines(&message.content));
    } else {
        lines.extend(message.lines.iter().map(rich_line));
    }
    lines.push(Line::raw(""));
    lines
}

fn wrapped_rows(width: usize, columns: usize) -> usize {
    1 + width.saturating_sub(1) / columns.max(1)
}

fn message_rows(message: &Message, columns: usize) -> usize {
    let body: usize = if message.lines.is_empty() {
        message
            .content
            .lines()
            .map(|line| wrapped_rows(line.width(), columns))
            .sum()
    } else {
        message
            .lines
            .iter()
            .map(|line| {
                wrapped_rows(
                    line.spans.iter().map(|span| span.text.width()).sum(),
                    columns,
                )
            })
            .sum()
    };
    2 + body // role and spacer
}

fn nav(frame: &mut Frame, ui: &mut Ui, area: Rect) {
    frame.render_widget(Block::default().style(Style::default().bg(BASE)), area);
    let mut x = area.x.saturating_add(1);
    for label in std::iter::once("OpenMates").chain(NAV.iter().copied()) {
        let width = (label.width() as u16 + 2).min(area.right().saturating_sub(x));
        if width == 0 {
            break;
        }
        let selected = ui.snapshot.state.view == label;
        let style = Style::default()
            .fg(if selected {
                Color::Rgb(255, 106, 72)
            } else {
                MUTED
            })
            .bg(BASE)
            .add_modifier(Modifier::BOLD);
        frame.render_widget(
            Paragraph::new(format!(" {label} ")).style(style),
            Rect::new(x, area.y, width, 1),
        );
        if label != "OpenMates" {
            ui.hit(
                Rect::new(x, area.y, width, 1),
                HitAction::Nav(label.to_owned()),
            );
        }
        x = x.saturating_add(width + 1);
    }
    let toggle = Rect::new(
        area.right().saturating_sub(10),
        area.y,
        9.min(area.width),
        1,
    );
    frame.render_widget(
        Paragraph::new("☰ sidebar").style(Style::default().fg(MUTED)),
        toggle,
    );
    ui.hit(toggle, HitAction::Sidebar);
}

fn sidebar(frame: &mut Frame, ui: &mut Ui, area: Rect) {
    if area.width == 0 {
        return;
    }
    let border = if ui.focus == Focus::Sidebar {
        ACCENT
    } else {
        MUTED
    };
    frame.render_widget(
        Block::default()
            .title(" Chats ")
            .borders(Borders::RIGHT)
            .border_style(Style::default().fg(border))
            .style(Style::default().bg(Color::Rgb(24, 31, 43))),
        area,
    );
    let inner = Rect::new(
        area.x + 1,
        area.y + 1,
        area.width.saturating_sub(3),
        area.height.saturating_sub(2),
    );
    let mut row = inner.y;
    for category in &ui.snapshot.state.categories {
        if row >= inner.bottom() {
            break;
        }
        let color = rgb(&category.color, ACCENT);
        let r = Rect::new(inner.x, row, inner.width, 1);
        frame.render_widget(
            Paragraph::new(format!(" ● {}", category.label)).style(Style::default().fg(color)),
            r,
        );
        ui.hits.push(Hit {
            rect: r,
            action: HitAction::Category(category.id.clone()),
        });
        row += 1;
    }
    if row < inner.bottom() {
        row += 1;
    }
    let chats = ui.snapshot.state.chats.clone();
    for (i, chat) in chats.iter().enumerate() {
        if row >= inner.bottom() {
            break;
        }
        let selected = ui.snapshot.state.selected_chat_id == chat.id
            || (ui.focus == Focus::Sidebar && ui.selected_sidebar == i);
        let r = Rect::new(inner.x, row, inner.width, 1);
        frame.render_widget(
            Paragraph::new(format!(
                "{} {}",
                if selected { "›" } else { " " },
                chat.title
            ))
            .style(
                Style::default()
                    .fg(if selected { Color::White } else { MUTED })
                    .bg(if selected {
                        Color::Rgb(48, 61, 78)
                    } else {
                        Color::Rgb(24, 31, 43)
                    }),
            ),
            r,
        );
        ui.hit(r, HitAction::Chat(chat.id.clone()));
        row += 1;
    }
}

fn body(frame: &mut Frame, ui: &mut Ui, area: Rect) {
    let state: &UiState = &ui.snapshot.state;
    let category = state.categories.iter().find(|c| c.id == state.category);
    let category_color = category.map(|c| rgb(&c.color, ACCENT)).unwrap_or(ACCENT);
    let center_width = area.width.min(120);
    let centered = Rect::new(
        area.x + (area.width - center_width) / 2,
        area.y,
        center_width,
        area.height,
    );
    frame.render_widget(Block::default().style(Style::default().bg(BASE)), area);
    if centered.height == 0 {
        return;
    }
    let title = Rect::new(centered.x, centered.y, centered.width, 1);
    frame.render_widget(
        Paragraph::new(format!(
            "←  {}  {}",
            state.title,
            category.map(|c| c.label.as_str()).unwrap_or("")
        ))
        .style(
            Style::default()
                .fg(category_color)
                .add_modifier(Modifier::BOLD),
        ),
        title,
    );
    ui.hits.push(Hit {
        rect: Rect::new(title.x, title.y, 2.min(title.width), 1),
        action: HitAction::Back,
    });
    let mut content_area = Rect::new(
        centered.x,
        centered.y + 1,
        centered.width,
        centered.height.saturating_sub(1),
    );
    let embeds = ui.embeds();
    let embed_items: Vec<(String, String, String)> = embeds
        .iter()
        .map(|e| (e.id.clone(), e.title.clone(), e.color.clone()))
        .collect();
    if !embed_items.is_empty() && content_area.height >= 5 {
        let cards = Rect::new(centered.x, centered.bottom() - 3, centered.width, 3);
        frame.render_widget(
            Block::default()
                .title(" Embeds  ← → Enter ")
                .borders(Borders::TOP)
                .border_style(Style::default().fg(MUTED)),
            cards,
        );
        let mut x = cards.x;
        let start = ui.selected_embed.saturating_sub(2);
        for (i, (id, title, color)) in embed_items.iter().enumerate().skip(start).take(5) {
            let width = (title.width() as u16 + 4)
                .min(24)
                .min(cards.right().saturating_sub(x));
            if width < 4 {
                break;
            }
            let r = Rect::new(x, cards.y + 1, width, 2);
            frame.render_widget(
                Paragraph::new(title.as_str())
                    .block(
                        Block::default()
                            .borders(Borders::ALL)
                            .border_style(Style::default().fg(rgb(color, ACCENT))),
                    )
                    .style(Style::default().fg(
                        if ui.focus == Focus::Embeds && i == ui.selected_embed {
                            Color::White
                        } else {
                            MUTED
                        },
                    )),
                r,
            );
            ui.hits.push(Hit {
                rect: r,
                action: HitAction::Embed(id.clone()),
            });
            x = x.saturating_add(width + 1);
        }
        content_area.height = content_area.height.saturating_sub(3);
    }
    let columns = content_area.width.max(1) as usize;
    let (lines, scroll, first_item): (Vec<Line<'static>>, u16, usize) = if state.view == "chats" {
        let target = content_area.height as usize * 2 + ui.scroll_up as usize + 8;
        let mut first = state.messages.len();
        let mut covered = 0;
        while first > 0 && covered < target {
            first -= 1;
            covered += message_rows(&state.messages[first], columns);
        }
        let lines: Vec<Line<'static>> = state.messages[first..]
            .iter()
            .flat_map(message_lines)
            .collect();
        let estimated: usize = lines
            .iter()
            .map(|line| wrapped_rows(line.width(), columns))
            .sum();
        let scroll = estimated
            .saturating_sub(content_area.height as usize)
            .saturating_sub(ui.scroll_up as usize)
            .min(u16::MAX as usize) as u16;
        (lines, scroll, first)
    } else {
        let total_lines = state.workspace_rows.len().saturating_mul(3);
        let first_line = total_lines
            .saturating_sub(content_area.height as usize)
            .saturating_sub(ui.scroll_up as usize);
        let first_item = first_line / 3;
        let last_item =
            (first_item + content_area.height as usize / 3 + 3).min(state.workspace_rows.len());
        let lines: Vec<Line<'static>> = state.workspace_rows[first_item..last_item]
            .iter()
            .enumerate()
            .flat_map(|(i, row)| {
                [
                    Line::styled(
                        clip(&row.label, content_area.width as usize),
                        Style::default()
                            .fg(rgb(&row.color, ACCENT))
                            .add_modifier(Modifier::BOLD)
                            .bg(
                                if ui.focus == Focus::Rows && ui.selected_row == first_item + i {
                                    Color::Rgb(48, 61, 78)
                                } else {
                                    BASE
                                },
                            ),
                    ),
                    Line::styled(
                        clip(&row.detail, content_area.width as usize),
                        Style::default().fg(MUTED),
                    ),
                    Line::raw(""),
                ]
            })
            .collect();
        (lines, (first_line % 3) as u16, first_item)
    };
    if state.view != "chats" {
        for (index, row) in state.workspace_rows[first_item..].iter().enumerate() {
            let y = content_area.y as isize + (index * 3) as isize - scroll as isize;
            if y >= content_area.bottom() as isize {
                break;
            }
            if y >= content_area.y as isize && y < content_area.bottom() as isize {
                ui.hits.push(Hit {
                    rect: Rect::new(
                        content_area.x,
                        y as u16,
                        content_area.width,
                        2.min(content_area.bottom() - y as u16),
                    ),
                    action: HitAction::WorkspaceRow(row.id.clone()),
                });
            }
        }
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .wrap(Wrap { trim: false })
            .scroll((scroll, 0)),
        content_area,
    );
}

fn composer(frame: &mut Frame, ui: &mut Ui, area: Rect) {
    frame.render_widget(Block::default().style(Style::default().bg(BASE)), area);
    let width = area.width.min(120);
    let rect = Rect::new(
        area.x + (area.width - width) / 2,
        area.y,
        width,
        area.height,
    );
    let style = Style::default().fg(if ui.focus == Focus::Composer {
        ACCENT
    } else {
        MUTED
    });
    let input = if ui.draft.is_empty() {
        "Message OpenMates…"
    } else {
        &ui.draft
    };
    frame.render_widget(
        Paragraph::new(input)
            .style(Style::default().fg(if ui.draft.is_empty() {
                MUTED
            } else {
                Color::White
            }))
            .block(
                Block::default()
                    .title(" Composer · Enter send · Alt+Enter newline ")
                    .borders(Borders::ALL)
                    .border_style(style),
            )
            .wrap(Wrap { trim: false }),
        rect,
    );
    ui.hit(rect, HitAction::Composer);
    if ui.focus == Focus::Composer && rect.width > 2 && rect.height > 2 {
        let last = ui.draft.rsplit('\n').next().unwrap_or("");
        let x = rect.x + 1 + (last.width() as u16).min(rect.width - 3);
        let y = rect.y + 1 + (ui.draft.matches('\n').count() as u16).min(rect.height - 3);
        frame.set_cursor_position((x, y));
    }
}

pub fn draw(frame: &mut Frame, ui: &mut Ui) {
    ui.hits.clear();
    let area = frame.area();
    frame.render_widget(Clear, area);
    let parts = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(1),
            Constraint::Length(5),
        ])
        .split(area);
    nav(frame, ui, parts[0]);
    let sidebar_width = if ui.snapshot.state.sidebar_open && area.width >= 70 {
        27
    } else {
        0
    };
    let columns = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Length(sidebar_width), Constraint::Min(1)])
        .split(parts[1]);
    sidebar(frame, ui, columns[0]);
    body(frame, ui, columns[1]);
    composer(frame, ui, parts[2]);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crossterm::event::{KeyEventKind, KeyEventState};
    use ratatui::{Terminal, backend::TestBackend};

    fn key(code: KeyCode, modifiers: KeyModifiers) -> KeyEvent {
        KeyEvent {
            code,
            modifiers,
            kind: KeyEventKind::Press,
            state: KeyEventState::NONE,
        }
    }
    fn sample() -> Ui {
        let mut s = Snapshot {
            v: 1,
            r#type: "snapshot".into(),
            epoch: 4,
            scope: "acct:team:chat".into(),
            ..Default::default()
        };
        s.state.chats.push(crate::model::Chat {
            id: "chat-1".into(),
            title: "One".into(),
            ..Default::default()
        });
        s.state.view = "chats".into();
        s.state.messages.push(Message {
            id: "m1".into(),
            role: "assistant".into(),
            content: "# Heading\n**Bold**".into(),
            ..Default::default()
        });
        Ui::new(s)
    }
    #[test]
    fn key_actions_carry_snapshot_fence() {
        let mut ui = sample();
        assert_eq!(
            ui.key(key(KeyCode::Char('x'), KeyModifiers::NONE))[0]
                .action(&ui.snapshot)
                .epoch,
            4
        );
        assert_eq!(
            ui.key(key(KeyCode::Enter, KeyModifiers::NONE))[0].name,
            "send_message"
        );
        assert_eq!(
            ui.key(key(KeyCode::Char('b'), KeyModifiers::CONTROL))[0].open,
            Some(true)
        );
        assert_eq!(
            ui.key(key(KeyCode::Enter, KeyModifiers::NONE))[0]
                .id
                .as_deref(),
            Some("chat-1")
        );
        assert_eq!(
            ui.key(key(KeyCode::Esc, KeyModifiers::NONE))[0].open,
            Some(false)
        );
    }
    #[test]
    fn message_headers_distinguish_local_remote_and_named_mate() {
        for (role, sender_name, expected) in [
            ("user", None, "You"),
            ("user", Some("Alex"), "Alex"),
            ("assistant", Some("Travel Mate"), "Travel Mate"),
            ("assistant", None, "OpenMates"),
        ] {
            let message = Message {
                role: role.into(),
                sender_name: sender_name.map(str::to_owned),
                ..Default::default()
            };
            let header = &message_lines(&message)[0];
            assert_eq!(header.spans[0].content.as_ref(), expected);
        }
    }
    #[test]
    fn drops_old_epoch() {
        let mut ui = sample();
        let mut incoming = ui.snapshot.clone();
        incoming.epoch = 3;
        assert!(!ui.update(incoming));
        assert_eq!(ui.snapshot.epoch, 4);
    }
    #[test]
    fn rendering_at_both_comparison_sizes() {
        for (w, h) in [(160, 50), (240, 70)] {
            let mut terminal = Terminal::new(TestBackend::new(w, h)).unwrap();
            let mut ui = sample();
            terminal.draw(|frame| draw(frame, &mut ui)).unwrap();
            let cells: String = terminal
                .backend()
                .buffer()
                .content()
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(
                cells.contains("Heading"),
                "{}",
                cells.chars().take(300).collect::<String>()
            );
        }
    }
    #[test]
    fn mouse_activates_chat_and_embed_hitboxes() {
        let mut ui = sample();
        ui.snapshot.state.sidebar_open = true;
        ui.snapshot.state.messages[0].embeds.push(Embed {
            id: "embed-1".into(),
            title: "Map".into(),
            ..Default::default()
        });
        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal.draw(|frame| draw(frame, &mut ui)).unwrap();
        for (name, expected_id) in [("chat", "chat-1"), ("embed", "embed-1")] {
            let rect = ui
                .hits
                .iter()
                .find_map(|hit| match (&hit.action, name) {
                    (HitAction::Chat(id), "chat") if id == expected_id => Some(hit.rect),
                    (HitAction::Embed(id), "embed") if id == expected_id => Some(hit.rect),
                    _ => None,
                })
                .unwrap();
            let actions = ui.mouse(MouseEvent {
                kind: MouseEventKind::Down(MouseButton::Left),
                column: rect.x,
                row: rect.y,
                modifiers: KeyModifiers::NONE,
            });
            assert_eq!(actions[0].id.as_deref(), Some(expected_id));
        }
    }
    #[test]
    fn large_workspace_projects_last_rows_and_keeps_pointer_ids() {
        let mut ui = sample();
        ui.snapshot.state.view = "tasks".into();
        ui.snapshot.state.workspace_rows = (0..500)
            .map(|i| crate::model::WorkspaceRow {
                id: format!("task-{i}"),
                label: format!("Task {i}"),
                detail: "Synthetic work".into(),
                color: "#f29f4b".into(),
            })
            .collect();
        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal.draw(|frame| draw(frame, &mut ui)).unwrap();
        let cells: String = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(cells.contains("Task 499"));
        let rect = ui
            .hits
            .iter()
            .find_map(|hit| match &hit.action {
                HitAction::WorkspaceRow(id) if id == "task-499" => Some(hit.rect),
                _ => None,
            })
            .unwrap();
        let actions = ui.mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        });
        assert_eq!(actions[0].name, "open_workspace_item");
        assert_eq!(actions[0].id.as_deref(), Some("task-499"));
    }
}
